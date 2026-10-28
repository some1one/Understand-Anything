//! Partition-scoped planning, batch preparation, and snapshot checks.
use crate::{
    Error, Result, array,
    persistence::{data_dir, read_json},
    updates::node_file_path,
};
use serde_json::{Value, json};
use std::{collections::BTreeSet, path::Path, process::Command};

fn git_paths(root: &Path, args: &[&str]) -> Result<BTreeSet<String>> {
    let output = Command::new("git").args(args).current_dir(root).output()?;
    if !output.status.success() {
        return Err(Error::Invalid(
            "Cannot establish partition source changes".into(),
        ));
    }
    let text = String::from_utf8(output.stdout).map_err(|e| Error::Invalid(e.to_string()))?;
    Ok(text
        .split('\0')
        .filter(|p| !p.is_empty())
        .map(str::to_owned)
        .collect())
}
/// Compare against this part's saved revision, never the merged metadata's newer
/// revision. This function does not write scratch files or modify saved graphs.
pub fn plan(root: &Path, part: &str, full: bool) -> Result<Value> {
    crate::partition_layout::validate_name(part)?;
    crate::partition_layout::verify_inventory(root)?;
    let data = data_dir(root);
    let inter = data.join("intermediate");
    let scan = read_json(&inter.join("scan-result.json"))?;
    if !scan["files"].is_array() || !array(&scan, "failures").is_empty() {
        return Err(Error::Invalid(
            "Partition preparation requires a complete scan".into(),
        ));
    }
    let inventory = inter
        .join("part-files")
        .join(format!("{}.json", part.replace('/', "~")));
    let inventory = if inventory.exists() {
        inventory
    } else {
        inventory.with_extension("txt")
    };
    let assigned: BTreeSet<_> = crate::file_lists::read(&inventory)?.into_iter().collect();
    let scanned: BTreeSet<_> = array(&scan, "files")
        .iter()
        .filter_map(|f| f["path"].as_str())
        .collect();
    if assigned.iter().any(|p| !scanned.contains(p.as_str())) {
        return Err(Error::Invalid(
            "Partition inventory is inconsistent with the scan".into(),
        ));
    }
    let path = data
        .join("partitions")
        .join(crate::partition::part_to_filename(part));
    let previous = if path.exists() {
        read_json(&path)?
    } else {
        Value::Null
    };
    if !previous.is_null() && (!previous["nodes"].is_array() || !previous["edges"].is_array()) {
        return Err(Error::Invalid("Invalid saved partition graph".into()));
    }
    let old_paths: BTreeSet<_> = array(&previous, "nodes")
        .iter()
        .filter(|n| n["stub"] != true)
        .filter_map(node_file_path)
        .collect();
    let base = previous["project"]["gitCommitHash"].as_str().unwrap_or("");
    let mut reason = if full {
        "full-request"
    } else if previous.is_null() {
        "new-part"
    } else {
        "source-changes"
    };
    let changed = if full || previous.is_null() {
        None
    } else if ![40, 64].contains(&base.len()) || !base.bytes().all(|b| b.is_ascii_hexdigit()) {
        reason = "unverifiable-baseline";
        None
    } else {
        let diff = git_paths(
            root,
            &[
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--relative",
                "--name-only",
                "--no-renames",
                "-z",
                base,
                "--",
                ".",
            ],
        );
        let untracked = git_paths(
            root,
            &[
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
                ".",
            ],
        );
        match (diff, untracked) {
            (Ok(mut paths), Ok(extra)) => {
                paths.extend(extra);
                Some(paths)
            }
            _ => {
                reason = "unverifiable-baseline";
                None
            }
        }
    };
    let targets: BTreeSet<_> = assigned
        .iter()
        .filter(|p| {
            changed
                .as_ref()
                .is_none_or(|paths| paths.contains(*p) || !old_paths.contains(*p))
        })
        .cloned()
        .collect();
    let removed: BTreeSet<_> = old_paths.difference(&assigned).cloned().collect();
    let retained: Vec<_> = array(&previous, "nodes")
        .iter()
        .filter(|node| {
            node["stub"] != true
                && node_file_path(node)
                    .is_some_and(|p| assigned.contains(&p) && !targets.contains(&p))
        })
        .cloned()
        .collect();
    let retained_ids: BTreeSet<_> = retained.iter().filter_map(|n| n["id"].as_str()).collect();
    // Preserve incoming references to replaced targets for reconciliation after
    // fresh nodes exist. Drop outgoing evidence owned by reanalyzed sources.
    let removed_ids: BTreeSet<_> = array(&previous, "nodes")
        .iter()
        .filter(|n| node_file_path(n).is_some_and(|p| removed.contains(&p)))
        .filter_map(|n| n["id"].as_str())
        .collect();
    let edges: Vec<_> = array(&previous, "edges")
        .iter()
        .filter(|e| {
            e["source"]
                .as_str()
                .is_some_and(|id| retained_ids.contains(id))
                && !e["target"]
                    .as_str()
                    .is_some_and(|id| removed_ids.contains(id))
        })
        .cloned()
        .collect();
    Ok(
        json!({"version":1,"part":part,"mode":if changed.is_some(){"incremental"}else{"full"},"reason":reason,"baseCommit":base,"filesToAnalyze":targets,"removedFiles":removed,"assignedFiles":assigned,"baseline":{"nodes":retained,"edges":edges}}),
    )
}

fn source_hashes(root: &Path, paths: &[String]) -> Result<Value> {
    use sha2::{Digest, Sha256};
    let mut hashes = serde_json::Map::new();
    for path in paths {
        hashes.insert(
            path.clone(),
            json!(format!(
                "{:x}",
                Sha256::digest(std::fs::read(root.join(path))?)
            )),
        );
    }
    Ok(Value::Object(hashes))
}
/// Publish a coherent batch plan, retaining the old scratch set for recovery.
pub fn prepare(root: &Path, part: &str, full: bool) -> Result<Value> {
    use std::fs;
    let inter = data_dir(root).join("intermediate");
    let _lock = crate::batch_files::lock(&inter)?;
    let plan = plan(root, part, full)?;
    let scan = read_json(&inter.join("scan-result.json"))?;
    for path in crate::strings(&plan["assignedFiles"]) {
        if !scan["importMap"][&path]
            .as_array()
            .is_some_and(|values| values.iter().all(Value::is_string))
        {
            return Err(Error::Invalid(format!(
                "Partition preparation requires a refreshed import map for {path}"
            )));
        }
    }
    let graph_path = data_dir(root)
        .join("partitions")
        .join(crate::partition::part_to_filename(part));
    let previous = if graph_path.exists() {
        read_json(&graph_path)?
    } else {
        Value::Null
    };
    let selected = crate::strings(&plan["filesToAnalyze"])
        .into_iter()
        .collect();
    let batches = crate::batching::compute_batches(root, &scan, Some(&selected));
    let hashes = source_hashes(root, &crate::strings(&plan["assignedFiles"]))?;
    let record = json!({"version":1,"part":part,"plan":plan,"previousGraph":previous,"scan":scan,"sourceHashes":hashes,"partitionLayout":crate::partition_layout::load(root)?});
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| Error::Invalid(e.to_string()))?
        .as_nanos();
    let staging = inter.join(format!(".part-prepare-{}-{stamp}", std::process::id()));
    fs::create_dir(&staging)?;
    for (name, value) in [
        ("part-update.json", &record),
        ("batches.json", &batches),
        ("batch-existing.json", &plan["baseline"]),
    ] {
        crate::persistence::write_json(&staging.join(name), value)?;
    }
    let managed = |name: &str| {
        (name.starts_with("batch-") && name.ends_with(".json"))
            || [
                "part-update.json",
                "part-edge-candidates.json",
                "batches.json",
                "assembled-graph.json",
            ]
            .contains(&name)
    };
    let mut old = vec![];
    for entry in fs::read_dir(&inter)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if managed(&name) {
            if !entry.file_type()?.is_file() {
                return Err(Error::Invalid(format!(
                    "Preparation artifact is not a regular file: {name}"
                )));
            }
            old.push(name);
        }
    }
    let backup = staging.join("previous");
    fs::create_dir(&backup)?;
    let mut moved = vec![];
    let mut installed = vec![];
    let result = (|| -> Result<()> {
        for name in &old {
            fs::rename(inter.join(name), backup.join(name))?;
            moved.push(name.clone());
        }
        for name in ["part-update.json", "batches.json", "batch-existing.json"] {
            fs::rename(staging.join(name), inter.join(name))?;
            installed.push(name);
        }
        Ok(())
    })();
    if let Err(error) = result {
        for name in installed {
            fs::rename(inter.join(name), staging.join(name))?;
        }
        for name in moved {
            fs::rename(backup.join(&name), inter.join(name))?;
        }
        return Err(error);
    }
    Ok(
        json!({"part":part,"mode":plan["mode"],"reason":plan["reason"],"filesToAnalyze":plan["filesToAnalyze"],"removedFiles":plan["removedFiles"],"totalBatches":batches["totalBatches"],"recoveryDirectory":staging}),
    )
}
/// Verify the snapshot before publishing a prepared part; legacy full analysis
/// without a preparation record still uses the ordinary symbol gate.
pub fn verify_preparation(root: &Path, part: &str, previous: &Value) -> Result<Option<Value>> {
    crate::partition_layout::verify_inventory(root)?;
    let inter = data_dir(root).join("intermediate");
    let path = inter.join("part-update.json");
    if !path.exists() {
        return Ok(None);
    }
    let record = read_json(&path)?;
    if record["partitionLayout"] != crate::partition_layout::load(root)? {
        return Err(Error::Invalid(
            "Partition layout changed during analysis; repartition and prepare again".into(),
        ));
    }
    if record["version"] != 1 || record["part"] != part || record["previousGraph"] != *previous {
        return Err(Error::Invalid(
            "Partition preparation no longer matches the saved graph; prepare this part again"
                .into(),
        ));
    }
    let scan = read_json(&inter.join("scan-result.json"))?;
    if record["scan"] != scan
        || record["sourceHashes"]
            != source_hashes(root, &crate::strings(&record["plan"]["assignedFiles"]))?
    {
        return Err(Error::Invalid(
            "Partition source or scan changed during analysis; preserve evidence and prepare again"
                .into(),
        ));
    }
    let current = plan(root, part, record["plan"]["mode"] == "full")?;
    if current["assignedFiles"] != record["plan"]["assignedFiles"] {
        return Err(Error::Invalid(
            "Partition inventory changed during analysis".into(),
        ));
    }
    Ok(Some(record))
}

pub fn retry_state(root: &Path, part: &str, preparation: &Value) -> Result<Option<Value>> {
    let path = data_dir(root)
        .join("intermediate")
        .join(format!("part-symbol-retry-{}.json", part.replace('/', "~")));
    if !path.exists() {
        return Ok(None);
    }
    let retry = read_json(&path)?;
    if retry["version"] != 1
        || !retry["graph"]["nodes"].is_array()
        || !retry["graph"]["edges"].is_array()
        || !retry["files"]
            .as_array()
            .is_some_and(|values| values.iter().all(Value::is_string))
    {
        return Err(Error::Invalid("Invalid partition repair marker".into()));
    }
    if retry["preparation"]["previousGraph"] != preparation["previousGraph"]
        || retry["preparation"]["sourceHashes"] != preparation["sourceHashes"]
    {
        return Ok(None);
    }
    Ok(Some(retry))
}
/// Prepare one repair attempt, retaining successful outputs and original evidence.
pub fn prepare_retry(root: &Path, part: &str) -> Result<Value> {
    use std::fs;
    let inter = data_dir(root).join("intermediate");
    let _lock = crate::batch_files::lock(&inter)?;
    let previous = read_json(
        &data_dir(root)
            .join("partitions")
            .join(crate::partition::part_to_filename(part)),
    )?;
    let preparation = verify_preparation(root, part, &previous)?
        .ok_or_else(|| Error::Invalid("Partition repair requires a prepared update".into()))?;
    if retry_state(root, part, &preparation)?.is_some() {
        return Err(Error::Invalid(
            "The single partition symbol repair attempt has already been used".into(),
        ));
    }
    let assembled = read_json(&inter.join("assembled-graph.json"))?;
    let candidates = read_json(&inter.join("part-edge-candidates.json"))?;
    if candidates["version"] != 1
        || candidates["preparation"] != preparation
        || candidates["graphHash"] != crate::incremental_symbols::edge_candidate_hash(&assembled)?
    {
        return Err(Error::Invalid(
            "Partition repair edge evidence is stale; rerun merging".into(),
        ));
    }
    let scan = &preparation["scan"];
    let known = array(scan, "files")
        .iter()
        .filter_map(|f| f["path"].as_str().map(str::to_owned))
        .collect();
    let graph = crate::assembly::build_part_graph(&assembled, part, &known, scan, "");
    if crate::incremental_symbols::validate_part_replacement(root, part, &previous, &graph, scan)
        .is_ok()
    {
        return Err(Error::Invalid(
            "No unresolved partition symbols need repair".into(),
        ));
    }
    let report = read_json(&inter.join(format!(
        "part-symbol-report-{}.json",
        part.replace('/', "~")
    )))?;
    if report["ok"] != false || !report["errors"].is_array() || !array(&report, "errors").is_empty()
    {
        return Err(Error::Invalid(
            "Partition source/identity errors must be resolved before repair".into(),
        ));
    }
    let paths: BTreeSet<_> = array(&report, "files")
        .iter()
        .filter(|f| f["ok"] != true)
        .filter_map(|f| f["filePath"].as_str().map(str::to_owned))
        .collect();
    let original: BTreeSet<_> = crate::strings(&preparation["plan"]["filesToAnalyze"])
        .into_iter()
        .collect();
    if paths.is_empty() || !paths.is_subset(&original) {
        return Err(Error::Invalid(
            "Partition repair files are outside the analyzed targets".into(),
        ));
    }
    let batches = crate::batching::compute_batches(root, scan, Some(&paths));
    let nodes: Vec<_> = array(&assembled, "nodes")
        .iter()
        .filter(|n| !node_file_path(n).is_some_and(|p| paths.contains(&p)))
        .cloned()
        .collect();
    let ids: BTreeSet<_> = nodes.iter().filter_map(|n| n["id"].as_str()).collect();
    let edges: Vec<_> = array(&assembled, "edges")
        .iter()
        .filter(|e| e["source"].as_str().is_some_and(|id| ids.contains(id)))
        .cloned()
        .collect();
    let marker = inter.join(format!("part-symbol-retry-{}.json", part.replace('/', "~")));
    let mut retry = json!({"version":1,"preparation":preparation,"graph":assembled,"edgeCandidates":candidates,"files":paths,"status":"preparing"});
    crate::persistence::write_json(&marker, &retry)?;
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| Error::Invalid(e.to_string()))?
        .as_nanos();
    let archive = inter.join(format!(".part-symbol-retry-{stamp}"));
    fs::create_dir(&archive)?;
    for entry in fs::read_dir(&inter)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if (name.starts_with("batch-") && name.ends_with(".json"))
            || [
                "batches.json",
                "assembled-graph.json",
                "part-edge-candidates.json",
            ]
            .contains(&name.as_str())
        {
            fs::rename(entry.path(), archive.join(name))?;
        }
    }
    crate::persistence::write_json(
        &inter.join("batch-existing.json"),
        &json!({"nodes":nodes,"edges":edges}),
    )?;
    crate::persistence::write_json(&inter.join("batches.json"), &batches)?;
    retry["status"] = json!("ready");
    crate::persistence::write_json(&marker, &retry)?;
    Ok(
        json!({"part":part,"symbolRepair":true,"filesToAnalyze":paths,"totalBatches":batches["totalBatches"],"symbolReport":report,"recoveryDirectory":archive}),
    )
}
