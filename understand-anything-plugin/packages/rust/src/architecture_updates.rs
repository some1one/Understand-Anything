//! Decide whether a merged partition update needs fresh architecture analysis.
use crate::{
    array, fingerprints,
    persistence::{data_dir, read_json, write_json},
    updates, Error, Result,
};
use serde_json::{json, Value};
use std::{collections::BTreeSet, path::Path};

fn paths(graph: &Value) -> BTreeSet<String> {
    array(graph, "nodes")
        .iter()
        .filter(|node| node["stub"] != true)
        .filter_map(updates::node_file_path)
        .collect()
}

pub fn prepare(root: &Path, full: bool) -> Result<Value> {
    let data = data_dir(root);
    let inter = data.join("intermediate");
    let current = read_json(&inter.join("assembled-graph.json"))?;
    let scan = read_json(&inter.join("scan-result.json"))?;
    if !current["nodes"].is_array()
        || !current["edges"].is_array()
        || !scan["files"].is_array()
        || !array(&scan, "failures").is_empty()
    {
        return Err(Error::Invalid(
            "Architecture planning requires a valid merged graph and complete scan".into(),
        ));
    }
    let current_paths = paths(&current);
    let scanned: BTreeSet<_> = array(&scan, "files")
        .iter()
        .filter_map(|f| f["path"].as_str())
        .collect();
    if current_paths.iter().any(|p| !scanned.contains(p.as_str())) {
        return Err(Error::Invalid(
            "Merged architecture inventory is inconsistent with the scan".into(),
        ));
    }
    let previous_path = data.join("knowledge-graph.json");
    let previous = if previous_path.exists() {
        read_json(&previous_path)?
    } else {
        Value::Null
    };
    let (store, _) = fingerprints::load_fingerprint_store(&data.join("fingerprints.json"))?;
    let baseline_valid = previous["nodes"].is_array()
        && previous["edges"].is_array()
        && previous["layers"].as_array().is_some_and(|layers| {
            layers.iter().any(|layer| {
                layer["id"].as_str().is_some_and(|id| !id.is_empty())
                    && layer["nodeIds"].as_array().is_some_and(|ids| {
                        ids.iter().any(|id| {
                            array(&previous, "nodes")
                                .iter()
                                .any(|node| node["id"] == *id)
                        })
                    })
            })
        })
        && store["files"].is_object()
        && previous["project"]["gitCommitHash"]
            .as_str()
            .is_some_and(|hash| !hash.is_empty() && store["gitCommitHash"] == hash);
    let mut decision = if full || !baseline_valid {
        json!({"action":"FULL_UPDATE","rerunArchitecture":true,"reason":if full {"Full analysis requested"} else {"No usable saved architecture and fingerprint baseline"}})
    } else {
        let old_paths = paths(&previous);
        let mut changes = vec![];
        for path in old_paths.union(&current_paths) {
            if !current_paths.contains(path) {
                changes
                    .push(json!({"filePath":path,"changeLevel":"STRUCTURAL","status":"deleted"}));
            } else {
                // Read errors must not masquerade as source deletion.
                let content = std::fs::read_to_string(root.join(path))?
                    .replace("\r\n", "\n")
                    .replace('\r', "\n");
                let stored = old_paths
                    .contains(path)
                    .then(|| store["files"].get(path))
                    .flatten();
                let (level, details) = stored
                    .map(|old| {
                        if old["contentHash"] == fingerprints::content_hash(&content) {
                            ("NONE", vec![])
                        } else {
                            let fingerprint = fingerprints::fingerprint_for_content(path, &content);
                            fingerprints::compare_fingerprints(old, &fingerprint)
                        }
                    })
                    .unwrap_or_else(|| {
                        (
                            "STRUCTURAL",
                            vec!["new file or missing fingerprint".to_owned()],
                        )
                    });
                changes.push(json!({"filePath":path,"changeLevel":level,"details":details,"status":if old_paths.contains(path) {"modified"} else {"new"}}));
            }
        }
        let mut result =
            fingerprints::classify_update_with_inventory(&changes, &old_paths, &current_paths);
        // FULL_UPDATE means rebuild here, rather than the auto-update hook's handoff.
        result["rerunArchitecture"] =
            json!(result["action"] == "FULL_UPDATE" || result["rerunArchitecture"] == true);
        result["fileChanges"] = json!(changes);
        result
    };
    if decision["rerunArchitecture"] == false {
        let layers = updates::reconcile_layers(
            array(&current, "nodes"),
            array(&current, "edges"),
            array(&previous, "layers"),
        );
        write_json(&inter.join("layers.json"), &json!(layers))?;
    }
    decision["skipAssembleReviewer"] =
        json!(!full && baseline_valid && decision["action"] != "FULL_UPDATE");
    write_json(&inter.join("architecture-update-plan.json"), &decision)?;
    Ok(decision)
}
