//! Folder partitioning and incremental part selection.
use crate::{Error, Result, persistence};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

pub fn posix(path: &str) -> String {
    let normalized = crate::imports::to_posix(path);
    let mut p = normalized.as_str();
    while let Some(rest) = p.strip_prefix("./") {
        p = rest;
    }
    p.trim_matches('/').to_owned()
}
pub fn partition_files(
    paths: &[String],
    sources: &[String],
    depth: Option<usize>,
) -> Result<BTreeMap<String, Vec<String>>> {
    if sources.is_empty() && depth.is_none() {
        return Err(Error::Invalid(
            "partition_files requires at least one of `sources` or `depth`".into(),
        ));
    }
    if depth == Some(0) {
        return Err(Error::Invalid("depth must be >= 1, got 0".into()));
    }
    let sources: BTreeSet<String> = sources
        .iter()
        .map(|s| posix(s))
        .filter(|s| !s.is_empty())
        .collect();
    let mut parts: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for path in paths {
        let p = posix(path);
        if p.is_empty() {
            continue;
        }
        let components: Vec<_> = p.split('/').filter(|s| !s.is_empty()).collect();
        let dirs = &components[..components.len() - 1];
        let key = if !sources.is_empty() {
            if let Some(src) = sources
                .iter()
                .filter(|s| p.starts_with(&format!("{s}/")))
                .max_by_key(|s| s.len())
            {
                let offset = src.split('/').count();
                let end = dirs.len().min(offset + depth.unwrap_or(1));
                let sub = &dirs[offset..end];
                if sub.is_empty() {
                    src.clone()
                } else {
                    format!("{src}/{}", sub.join("/"))
                }
            } else {
                "_root".into()
            }
        } else {
            let key = dirs[..dirs.len().min(depth.unwrap_or(1))].join("/");
            if key.is_empty() { "_root".into() } else { key }
        };
        parts.entry(key).or_default().push(p);
    }
    for files in parts.values_mut() {
        files.sort();
    }
    Ok(parts)
}
pub fn part_to_filename(part: &str) -> String {
    format!("{}.knowledge-graph.json", part.replace('/', "~"))
}
pub fn filename_to_part(filename: &str) -> String {
    filename
        .strip_suffix(".knowledge-graph.json")
        .unwrap_or(filename)
        .replace('~', "/")
}
pub fn detect_layout(paths: &[String]) -> Value {
    let paths: Vec<String> = paths
        .iter()
        .map(|p| {
            p.replace('\\', "/")
                .trim()
                .trim_start_matches(['.', '/'])
                .trim_matches('/')
                .to_owned()
        })
        .filter(|p| !p.is_empty())
        .collect();
    let markers = ["pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json"];
    let manifests = [
        "package.json",
        "pyproject.toml",
        "go.mod",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
    ];
    let mut packages = BTreeSet::new();
    for p in &paths {
        let seg: Vec<_> = p.split('/').collect();
        if seg.len() >= 3
            && ["packages", "apps", "services", "libs"].contains(&seg[0])
            && manifests.contains(seg.last().unwrap())
        {
            packages.insert(seg[..2].join("/"));
        }
    }
    if packages.len() >= 2 || paths.iter().any(|p| markers.contains(&p.as_str())) {
        return json!({"detectedRoots": packages, "recommendation": {"sourceFolders": null, "splitDepth": 2}});
    }
    for src in ["src", "lib", "app", "source"] {
        if paths.iter().any(|p| p.starts_with(&format!("{src}/"))) {
            return json!({"detectedRoots": [src], "recommendation": {"sourceFolders": [src], "splitDepth": 1}});
        }
    }
    json!({"detectedRoots": [], "recommendation": {"sourceFolders": null, "splitDepth": 1}})
}
pub fn affected_parts(
    changed: &[String],
    sources: &[String],
    depth: Option<usize>,
    included: &[String],
) -> Result<Vec<String>> {
    if changed.is_empty() {
        return Ok(vec![]);
    }
    Ok(partition_files(changed, sources, depth)?
        .into_keys()
        .filter(|p| included.is_empty() || included.contains(p))
        .collect())
}
pub fn parts_to_process(root: &Path, full: bool, changed: &[String]) -> Result<Vec<String>> {
    let config = persistence::load_config(root);
    let included = crate::strings(&config["includedParts"]);
    if full
        || changed.is_empty()
        || changed
            .iter()
            .any(|p| crate::context_helpers::is_ignore_file(p))
    {
        return Ok(included);
    }
    let mut parts: BTreeSet<_> = affected_parts(
        changed,
        &crate::strings(&config["sourceFolders"]),
        config["splitDepth"].as_u64().map(|d| d as usize),
        &included,
    )?
    .into_iter()
    .collect();
    for p in included {
        if !crate::persistence::data_dir(&root)
            .join("partitions")
            .join(part_to_filename(&p))
            .exists()
        {
            parts.insert(p);
        }
    }
    Ok(parts.into_iter().collect())
}
pub fn apply_updates(config: &Value, args: &[String]) -> Result<Value> {
    let mut out = config.clone();
    for arg in args {
        let (key, raw) = arg
            .split_once('=')
            .ok_or_else(|| Error::Invalid(format!("Unknown argument: {arg}")))?;
        let csv = || {
            raw.split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .collect::<Vec<_>>()
        };
        match key {
            "--source" => {
                let vals = csv();
                out["sourceFolders"] = if vals.is_empty() {
                    Value::Null
                } else {
                    json!(vals)
                };
            }
            "--depth" => {
                out["splitDepth"] = if raw.trim().is_empty() {
                    Value::Null
                } else {
                    json!(
                        raw.trim()
                            .parse::<i64>()
                            .map_err(|e| Error::Invalid(e.to_string()))?
                    )
                }
            }
            "--parts" => out["includedParts"] = json!(csv()),
            "--auto-update" => out["autoUpdate"] = json!(raw.trim().eq_ignore_ascii_case("true")),
            _ => return Err(Error::Invalid(format!("Unknown argument: {arg}"))),
        }
    }
    Ok(out)
}
