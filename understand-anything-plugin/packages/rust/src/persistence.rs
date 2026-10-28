//! JSON artifact persistence; extension fields are retained.
use crate::{Error, Result};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};
pub const UA_DIR: &str = ".ua";
pub const LEGACY_UA_DIR: &str = ".understand-anything";

/// Select one artifact directory for the whole project, including optional files.
/// Existing legacy projects stay in place; new projects use `.ua`.
pub fn data_dir(root: &Path) -> PathBuf {
    let current = root.join(UA_DIR);
    let legacy = root.join(LEGACY_UA_DIR);
    if current.is_dir() || !legacy.is_dir() {
        current
    } else {
        legacy
    }
}
pub fn read_json(path: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}
pub fn write_json(path: &Path, value: &Value) -> Result<()> {
    fs::write(path, serde_json::to_string_pretty(value)?)?;
    Ok(())
}
/// Archive the complete previous bytes before atomically publishing a graph.
/// History lives outside scratch, so analysis cleanup cannot discard recovery.
pub fn publish_graph(root: &Path, name: &str, value: &Value) -> Result<Option<PathBuf>> {
    if Path::new(name).components().any(|c| !matches!(c, std::path::Component::Normal(_))) {
        return Err(Error::Invalid("Graph destination must be a relative artifact path".into()));
    }
    let data = data_dir(root);
    let path = data.join(name);
    let parent = path.parent().ok_or_else(|| Error::Invalid("Missing graph parent".into()))?;
    fs::create_dir_all(parent)?;
    let staged = tempfile::NamedTempFile::new_in(parent)?;
    write_json(staged.path(), value)?;
    staged.as_file().sync_all()?;
    let archived = if path.exists() {
        let bytes = fs::read(&path)?;
        let history = data.join("history").join(name.strip_suffix(".json").unwrap_or(name));
        fs::create_dir_all(&history)?;
        let prefix = format!("{}-", chrono::Utc::now().format("%Y%m%dT%H%M%S%.9fZ"));
        let directory = tempfile::Builder::new().prefix(&prefix).tempdir_in(&history)?.keep();
        let backup = directory.join(path.file_name().ok_or_else(|| Error::Invalid("Missing graph filename".into()))?);
        fs::write(&backup, bytes)?;
        fs::OpenOptions::new().write(true).open(&backup)?.sync_all()?;
        write_json(&directory.join("recovery.json"), &json!({
            "originalArtifact":name, "archivedAt":crate::now_iso(),
            "instructions":"Stop analysis, copy the archived graph back to originalArtifact under the project data directory, and refresh the selected-part merge and query caches as needed."
        }))?;
        for input in ["config.json", "partition-layout.json"] {
            if data.join(input).is_file() { fs::copy(data.join(input), directory.join(input))?; }
        }
        Some(backup)
    } else { None };
    staged.persist(&path).map_err(|e| e.error)?;
    Ok(archived)
}
pub fn load_optional(root: &Path, name: &str) -> Result<Option<Value>> {
    let path = data_dir(root).join(name);
    if !path.exists() {
        return Ok(None);
    }
    read_json(&path).map(Some)
}
pub fn save_artifact(root: &Path, name: &str, value: &Value) -> Result<()> {
    let dir = data_dir(root);
    fs::create_dir_all(&dir)?;
    write_json(&dir.join(name), value)
}
pub fn load_config(root: &Path) -> Value {
    load_optional(root, "config.json")
        .ok()
        .flatten()
        .unwrap_or_else(|| json!({"autoUpdate": false}))
}
pub fn save_config(root: &Path, value: &Value) -> Result<()> {
    save_artifact(root, "config.json", value)
}
pub fn load_fingerprints(root: &Path) -> Option<Value> {
    load_optional(root, "fingerprints.json").ok().flatten()
}
pub fn save_fingerprints(root: &Path, value: &Value) -> Result<()> {
    save_artifact(root, "fingerprints.json", value)
}
pub fn load_meta(root: &Path) -> Result<Option<Value>> {
    load_optional(root, "meta.json")
}
pub fn save_meta(root: &Path, value: &Value) -> Result<()> {
    save_artifact(root, "meta.json", value)
}
pub fn sanitize_file_paths(graph: &Value, root: &Path) -> Value {
    let mut out = graph.clone();
    let mut nodes = crate::array(graph, "nodes").to_vec();
    for node in &mut nodes {
        if let Some(path) = node["filePath"].as_str() {
            let p = Path::new(path);
            if p.is_absolute() {
                let root_text = root.to_string_lossy();
                let relative = if path.starts_with(root_text.as_ref()) {
                    // Preserve the reference's lexical prefix and relpath behavior.
                    let normalize = |p: &Path| {
                        let absolute = if p.is_absolute() {
                            p.to_path_buf()
                        } else {
                            std::env::current_dir().unwrap_or_default().join(p)
                        };
                        let mut parts = Vec::new();
                        for c in absolute.components() {
                            match c {
                                std::path::Component::Normal(s) => parts.push(s.to_os_string()),
                                std::path::Component::ParentDir => {
                                    parts.pop();
                                }
                                _ => {}
                            }
                        }
                        parts
                    };
                    let from = normalize(root);
                    let to = normalize(p);
                    let common = from.iter().zip(&to).take_while(|(a, b)| a == b).count();
                    let mut relative = std::path::PathBuf::new();
                    for _ in common..from.len() {
                        relative.push("..");
                    }
                    for part in &to[common..] {
                        relative.push(part);
                    }
                    if relative.as_os_str().is_empty() {
                        ".".into()
                    } else {
                        relative.to_string_lossy().into_owned()
                    }
                } else {
                    p.file_name()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .into_owned()
                };
                node["filePath"] = json!(relative);
            }
        }
    }
    out["nodes"] = json!(nodes);
    out
}
pub fn save_graph(root: &Path, graph: &Value) -> Result<()> {
    publish_graph(
        root,
        "knowledge-graph.json",
        &sanitize_file_paths(graph, root),
    )?;
    crate::query_dictionary::refresh(
        &crate::persistence::data_dir(&root).join("knowledge-graph.json"),
    )?;
    Ok(())
}
pub fn save_domain_graph(root: &Path, graph: &Value) -> Result<()> {
    publish_graph(root, "domain-graph.json", &sanitize_file_paths(graph, root))?;
    Ok(())
}
pub fn load_graph(root: &Path, validate: bool) -> Result<Option<Value>> {
    load_graph_named(root, "knowledge-graph.json", validate)
}
pub fn load_domain_graph(root: &Path, validate: bool) -> Result<Option<Value>> {
    load_graph_named(root, "domain-graph.json", validate)
}
fn load_graph_named(root: &Path, name: &str, validate: bool) -> Result<Option<Value>> {
    let Some(graph) = load_optional(root, name)? else {
        return Ok(None);
    };
    if !validate {
        return Ok(Some(graph));
    }
    let result = crate::validation::validate_graph(&graph);
    if result["success"] == true {
        Ok(Some(result["data"].clone()))
    } else {
        Err(Error::Invalid(format!(
            "Invalid {}: {}",
            if name == "knowledge-graph.json" {
                "knowledge graph"
            } else {
                "domain graph"
            },
            result["fatal"].as_str().unwrap_or("unknown error")
        )))
    }
}
