//! Architecture input inventory; its enumeration policy differs from scan_project.
use crate::{Result, scan::IgnoreFilter, strings, tables};
use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
pub fn infer_node_type(path: &str) -> &'static str {
    let p = path.replace('\\', "/");
    let low = p.to_lowercase();
    let base = p.rsplit('/').next().unwrap_or("");
    let blow = base.to_lowercase();
    let framed = format!("/{low}");
    let table = &tables()["constants"];
    let contains = |key: &str, v: &str| strings(&table[key]).iter().any(|x| x == v);
    let suffix = |key: &str| strings(&table[key]).iter().any(|x| low.ends_with(x));
    if framed.contains("/.github/workflows/")
        || contains("CI_FILENAMES", &blow)
        || blow == "jenkinsfile"
        || strings(&table["CI_DIR_SEGMENTS"])
            .iter()
            .any(|s| framed.contains(&format!("/{s}/")))
    {
        return "pipeline";
    }
    if base == "Dockerfile"
        || blow.starts_with("dockerfile.")
        || blow.starts_with("docker-compose")
        || suffix("INFRA_EXTENSIONS")
        || blow == "makefile"
        || low.split('/').any(|s| contains("INFRA_DIR_SEGMENTS", s))
    {
        return "service";
    }
    if suffix("SCHEMA_EXTENSIONS") {
        return "schema";
    }
    if suffix("DOC_EXTENSIONS") {
        return "document";
    }
    if contains("NODE_TYPE_CONFIG_FILENAMES", &blow)
        || suffix("NODE_TYPE_CONFIG_EXTENSIONS")
        || strings(&table["CONFIG_DOTFILE_PREFIXES"])
            .iter()
            .any(|p| blow.starts_with(p))
    {
        return "config";
    }
    "file"
}
pub fn list_project_files(root: &Path, respect_gitignore: bool) -> Result<Vec<String>> {
    if respect_gitignore
        && let Ok(output) = Command::new("git")
            .arg("-C")
            .arg(root)
            .args(["ls-files", "-co", "--exclude-standard", "-z"])
            .output()
        && output.status.success()
    {
        return Ok(String::from_utf8_lossy(&output.stdout)
            .split('\0')
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect());
    }
    let patterns = if respect_gitignore {
        fs::read_to_string(root.join(".gitignore")).unwrap_or_default()
    } else {
        String::new()
    };
    let filter = IgnoreFilter::new(&patterns.lines().map(str::to_owned).collect::<Vec<_>>())?;
    Ok(walkdir::WalkDir::new(root)
        .sort_by_file_name()
        .into_iter()
        .filter_entry(|e| e.depth() == 0 || !e.file_type().is_dir() || e.file_name() != ".git")
        .filter_map(|e| e.ok())
        .filter(|e| e.file_type().is_file() || e.file_type().is_symlink() && !e.path().is_dir())
        .filter_map(|e| {
            e.path()
                .strip_prefix(root)
                .ok()
                .map(|p| p.to_string_lossy().replace('\\', "/"))
        })
        .filter(|p| !filter.is_ignored(p))
        .collect())
}
pub fn build_file_nodes(files: &[String]) -> Vec<Value> {
    let mut paths = files.to_vec();
    paths.sort();
    paths.iter().map(|p|{let t=infer_node_type(p);json!({"id":format!("{t}:{p}"),"type":t,"name":p.rsplit('/').next().unwrap_or(p),"filePath":p,"summary":"","tags":[]})}).collect()
}
pub fn generate(
    root: &Path,
    include: &[String],
    exclude: &[String],
    respect_gitignore: bool,
) -> Result<Value> {
    let inc = IgnoreFilter::new(include)?;
    let exc = IgnoreFilter::new(exclude)?;
    let files: Vec<_> = list_project_files(root, respect_gitignore)?
        .into_iter()
        .filter(|p| (include.is_empty() || inc.is_ignored(p)) && !exc.is_ignored(p))
        .collect();
    Ok(json!({"fileNodes":build_file_nodes(&files),"importEdges":[],"allEdges":[]}))
}
