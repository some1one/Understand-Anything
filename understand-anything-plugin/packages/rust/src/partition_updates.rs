//! Read-only preparation of partition-scoped incremental analysis.
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
