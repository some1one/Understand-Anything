//! Git revision staleness and file-keyed graph replacement.
use crate::array;
use serde_json::{Value, json};
use std::{collections::BTreeSet, path::Path, process::Command};
pub fn get_changed_files(root: &Path, last_commit: &str) -> Vec<String> {
    match Command::new("git")
        .args(["diff", &format!("{last_commit}..HEAD"), "--name-only"])
        .current_dir(root)
        .output()
    {
        Ok(out) if out.status.success() => String::from_utf8_lossy(&out.stdout)
            .lines()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect(),
        _ => vec![],
    }
}
pub fn is_stale(root: &Path, last_commit: &str) -> Value {
    let changed = get_changed_files(root, last_commit);
    json!({"stale":!changed.is_empty(),"changedFiles":changed})
}
pub fn merge_graph_update(
    existing: &Value,
    changed_paths: &[String],
    new_nodes: &[Value],
    new_edges: &[Value],
    commit: &str,
) -> Value {
    let changed: BTreeSet<_> = changed_paths.iter().map(String::as_str).collect();
    let removed: BTreeSet<_> = array(existing, "nodes")
        .iter()
        .filter(|n| n["filePath"].as_str().is_some_and(|s| changed.contains(s)))
        .filter_map(|n| n["id"].as_str())
        .collect();
    let nodes: Vec<_> = array(existing, "nodes")
        .iter()
        .filter(|n| !removed.contains(n["id"].as_str().unwrap_or("")))
        .chain(new_nodes)
        .cloned()
        .collect();
    let edges: Vec<_> = array(existing, "edges")
        .iter()
        .filter(|e| {
            !removed.contains(e["source"].as_str().unwrap_or(""))
                && !removed.contains(e["target"].as_str().unwrap_or(""))
        })
        .chain(new_edges)
        .cloned()
        .collect();
    let mut merged = existing.clone();
    if !merged["project"].is_object() {
        merged["project"] = json!({});
    }
    merged["project"]["gitCommitHash"] = json!(commit);
    merged["project"]["analyzedAt"] = json!(crate::now_iso());
    merged["nodes"] = json!(nodes);
    merged["edges"] = json!(edges);
    merged
}
