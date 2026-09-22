//! SHA-256 structural fingerprint comparison and incremental-update decisions.
use crate::{array, strings};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
pub fn content_hash(content: &str) -> String {
    format!("{:x}", Sha256::digest(content.as_bytes()))
}
pub fn extract_file_fingerprint(path: &str, content: &str, analysis: Option<&Value>) -> Value {
    let empty = json!({});
    let a = analysis.unwrap_or(&empty);
    let exports: Vec<_> = array(a, "exports")
        .iter()
        .map(|e| e["name"].clone())
        .collect();
    let functions:Vec<_>=array(a,"functions").iter().map(|f|json!({"name":f["name"],"params":strings(&f["params"]),"returnType":f["returnType"],"exported":exports.contains(&f["name"]),"lineCount":f["lineRange"][1].as_i64().unwrap_or(0)-f["lineRange"][0].as_i64().unwrap_or(0)+1})).collect();
    let classes:Vec<_>=array(a,"classes").iter().map(|c|json!({"name":c["name"],"methods":strings(&c["methods"]),"properties":strings(&c["properties"]),"exported":exports.contains(&c["name"]),"lineCount":c["lineRange"][1].as_i64().unwrap_or(0)-c["lineRange"][0].as_i64().unwrap_or(0)+1})).collect();
    let imports: Vec<_> = array(a, "imports")
        .iter()
        .map(|i| json!({"source":i["source"],"specifiers":strings(&i["specifiers"])}))
        .collect();
    json!({"filePath":path,"contentHash":content_hash(content),"functions":functions,"classes":classes,"imports":imports,"exports":exports,"totalLines":content.split('\n').count(),"hasStructuralAnalysis":analysis.is_some()})
}
fn signature(fp: &Value) -> Value {
    let mut out = json!({});
    for (key, fields) in [
        (
            "functions",
            vec!["name", "params", "returnType", "exported"],
        ),
        ("classes", vec!["name", "methods", "properties", "exported"]),
        ("imports", vec!["source", "specifiers"]),
    ] {
        let mut sig: Vec<_> = array(fp, key)
            .iter()
            .map(|item| {
                let row: Vec<_> = fields
                    .iter()
                    .map(|field| match *field {
                        "name" | "source" => json!(item[field].as_str().unwrap_or("")),
                        "params" | "methods" | "properties" | "specifiers" => {
                            json!(strings(&item[field]))
                        }
                        "exported" => json!(item[field].as_bool().unwrap_or(false)),
                        _ => item[field].clone(),
                    })
                    .collect();
                json!(row)
            })
            .collect();
        sig.sort_by_key(Value::to_string);
        out[key] = json!(sig);
    }
    let mut exports = strings(&fp["exports"]);
    exports.sort();
    out["exports"] = json!(exports);
    out
}
fn names(fp: &Value, key: &str, field: &str) -> BTreeSet<String> {
    array(fp, key)
        .iter()
        .map(|f| f[field].as_str().unwrap_or("").into())
        .collect()
}
pub fn compare_fingerprints(old: &Value, new: &Value) -> (&'static str, Vec<String>) {
    if old["contentHash"] == new["contentHash"] {
        return ("NONE", vec![]);
    }
    if old["hasStructuralAnalysis"] != true || new["hasStructuralAnalysis"] != true {
        return (
            "STRUCTURAL",
            vec!["no structural support — treated as structural".into()],
        );
    }
    if signature(old) == signature(new) {
        return (
            "COSMETIC",
            vec!["internal logic or formatting changed".into()],
        );
    }
    let mut details = vec![];
    for (key, label) in [("functions", "function"), ("classes", "class")] {
        let a = names(old, key, "name");
        let b = names(new, key, "name");
        for name in b.difference(&a) {
            details.push(format!("new {label}: {name}"));
        }
        for name in a.difference(&b) {
            details.push(format!("removed {label}: {name}"));
        }
    }
    if strings(&old["exports"])
        .into_iter()
        .collect::<BTreeSet<_>>()
        != strings(&new["exports"])
            .into_iter()
            .collect::<BTreeSet<_>>()
    {
        details.push("exports changed".into());
    }
    if names(old, "imports", "source") != names(new, "imports", "source") {
        details.push("imports changed".into());
    }
    if details.is_empty() {
        details.push("signature changed".into());
    }
    ("STRUCTURAL", details)
}
fn directory(path: &str) -> &str {
    path.rsplit_once('/').map(|(d, _)| d).unwrap_or("")
}
pub fn classify_update(changes: &[Value], graph_paths: &BTreeSet<String>) -> Value {
    let structural: Vec<_> = changes
        .iter()
        .filter(|c| c["changeLevel"] == "STRUCTURAL")
        .collect();
    let count = structural.len();
    let result = |action: &str, rerun: bool, reason: String| json!({"action":action,"rerunArchitecture":rerun,"reason":reason});
    if count == 0 {
        return result("SKIP", false, "No structural changes detected.".into());
    }
    if count > 30 || (!graph_paths.is_empty() && count as f64 > 0.5 * graph_paths.len() as f64) {
        return result(
            "FULL_UPDATE",
            false,
            format!(
                "{count} files have structural changes — major restructuring; recommend a full rebuild."
            ),
        );
    }
    let known: BTreeSet<_> = graph_paths.iter().map(|p| directory(p)).collect();
    let deleted: BTreeSet<_> = structural
        .iter()
        .filter(|c| c["status"] == "deleted")
        .filter_map(|c| c["filePath"].as_str())
        .collect();
    let surviving: BTreeSet<_> = graph_paths
        .iter()
        .filter(|p| !deleted.contains(p.as_str()))
        .map(|p| directory(p))
        .collect();
    let new: BTreeSet<_> = structural
        .iter()
        .filter(|c| c["status"] == "new")
        .filter_map(|c| c["filePath"].as_str())
        .map(directory)
        .filter(|d| !known.contains(d))
        .collect();
    let removed: BTreeSet<_> = deleted
        .iter()
        .map(|p| directory(p))
        .filter(|d| known.contains(d) && !surviving.contains(d))
        .collect();
    if !new.is_empty() || !removed.is_empty() || count > 10 {
        let reason = if !new.is_empty() || !removed.is_empty() {
            format!(
                "{count} structural file(s) span directory-level changes ({} new, {} removed directories) — re-running architecture.",
                new.len(),
                removed.len()
            )
        } else {
            format!(
                "{count} structural files exceed the partial limit of 10 — re-running architecture."
            )
        };
        return result("ARCHITECTURE_UPDATE", true, reason);
    }
    result(
        "PARTIAL_UPDATE",
        false,
        format!("{count} file(s) have localized structural changes."),
    )
}
pub fn fingerprint_for_content(path: &str, content: &str) -> Value {
    extract_file_fingerprint(
        path,
        content,
        crate::structure::analyze_file(path, content).as_ref(),
    )
}
pub fn fingerprint_for_path(root: &std::path::Path, rel: &str) -> Option<Value> {
    let content = std::fs::read_to_string(root.join(rel))
        .ok()?
        .replace("\r\n", "\n")
        .replace('\r', "\n");
    Some(fingerprint_for_content(rel, &content))
}
pub fn build_fingerprint_store(root: &std::path::Path, paths: &[String], commit: &str) -> Value {
    let files: serde_json::Map<_, _> = paths
        .iter()
        .filter_map(|p| fingerprint_for_path(root, p).map(|fp| (p.clone(), fp)))
        .collect();
    json!({"version":"1.0.0","gitCommitHash":commit,"generatedAt":crate::now_iso(),"files":files})
}
pub fn classify_file_change(root: &std::path::Path, rel: &str, stored: Option<&Value>) -> Value {
    match fingerprint_for_path(root, rel) {
        None => {
            json!({"filePath":rel,"changeLevel":"STRUCTURAL","status":"deleted","details":["file deleted"]})
        }
        Some(current) => match stored {
            None => {
                json!({"filePath":rel,"changeLevel":"STRUCTURAL","status":"new","details":["new file"]})
            }
            Some(old) => {
                let (level, details) = compare_fingerprints(old, &current);
                json!({"filePath":rel,"changeLevel":level,"status":"modified","details":details})
            }
        },
    }
}
pub fn load_fingerprint_store(path: &std::path::Path) -> crate::Result<(Value, bool)> {
    if !path.exists() {
        return Ok((json!({"version":"1.0.0","files":{}}), false));
    }
    let raw = std::fs::read_to_string(path)?;
    if raw.trim().is_empty() {
        return Ok((json!({"version":"1.0.0","files":{}}), false));
    }
    let mut store: Value = serde_json::from_str(&raw)?;
    if !store.is_object() {
        store = json!({"files":{}});
    }
    if store.get("files").is_none() {
        store["files"] = json!({});
    }
    Ok((store, true))
}
pub fn patch_fingerprint_store(
    store: &mut Value,
    root: &std::path::Path,
    changed: &[String],
) -> crate::Result<()> {
    if store.get("files").is_none() {
        store["files"] = json!({});
    }
    let files = store["files"]
        .as_object_mut()
        .ok_or_else(|| crate::Error::Invalid("fingerprint files must be an object".into()))?;
    for rel in changed {
        if let Some(fp) = fingerprint_for_path(root, rel) {
            files.insert(rel.clone(), fp);
        } else {
            files.remove(rel);
        }
    }
    Ok(())
}
pub fn save_fingerprint_store(
    path: &std::path::Path,
    store: &Value,
    existed: bool,
    before: usize,
) -> crate::Result<()> {
    if existed && before == 0 {
        return Err(crate::Error::Invalid(
            "fingerprints.json existed and was non-empty but loaded as {} — refusing to overwrite"
                .into(),
        ));
    }
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    crate::persistence::write_json(path, store)
}
pub fn patch_and_save_fingerprints(
    path: &std::path::Path,
    root: &std::path::Path,
    changed: &[String],
    commit: Option<&str>,
) -> crate::Result<(usize, usize)> {
    let (mut store, existed) = load_fingerprint_store(path)?;
    let before = store["files"].as_object().map_or(0, |o| o.len());
    patch_fingerprint_store(&mut store, root, changed)?;
    if let Some(commit) = commit {
        store["gitCommitHash"] = json!(commit);
    }
    let after = store["files"].as_object().map_or(0, |o| o.len());
    save_fingerprint_store(path, &store, existed, before)?;
    Ok((before, after))
}
