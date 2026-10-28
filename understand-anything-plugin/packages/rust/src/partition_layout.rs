//! User-owned partition definitions, independent of generated graph artifacts.
use crate::{Error, Result, partition, persistence, scan::IgnoreFilter};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};

fn invalid(message: &str) -> Error {
    Error::Invalid(format!("Invalid partition layout: {message}"))
}
pub fn validate_name(name: &str) -> Result<()> {
    if name.is_empty()
        || name.trim() != name
        || name.chars().any(|c| c.is_control() || ",~\\".contains(c))
        || name
            .split('/')
            .any(|s| s.is_empty() || s == "." || s == "..")
    {
        return Err(invalid(
            "part names must be nonempty relative names without comma, ~, backslash or dot components",
        ));
    }
    Ok(())
}
fn patterns(value: &Value, required: bool) -> Result<Vec<String>> {
    if value.is_null() && !required {
        return Ok(vec![]);
    }
    let entries = value
        .as_array()
        .ok_or_else(|| invalid("include/exclude must be string arrays"))?;
    if required && entries.is_empty() {
        return Err(invalid(
            "each named part requires at least one include pattern",
        ));
    }
    let mut out = vec![];
    for entry in entries {
        let p = entry
            .as_str()
            .ok_or_else(|| invalid("patterns must be strings"))?;
        if p.trim().is_empty()
            || p.starts_with(['!', '#'])
            || p.contains('\\')
            || p.chars().any(char::is_control)
            || p.split('/').any(|s| s == "..")
        {
            return Err(invalid(
                "use relative gitignore patterns; use exclude rather than ! negation",
            ));
        }
        out.push(p.to_owned());
    }
    IgnoreFilter::new(&out)?;
    Ok(out)
}
pub fn validate(layout: &Value) -> Result<()> {
    if !layout.is_object() {
        return Err(invalid("expected an object"));
    }
    if layout.get("version").is_some_and(|v| v != 1) {
        return Err(invalid("unsupported version"));
    }
    if layout
        .get("mode")
        .is_some_and(|mode| !matches!(mode.as_str(), Some("custom" | "hybrid")))
    {
        return Err(invalid("mode must be custom or hybrid"));
    }
    if let Some(groups) = layout.get("partitions") {
        let groups = groups
            .as_object()
            .ok_or_else(|| invalid("partitions must be a named object"))?;
        if groups.is_empty() {
            return Err(invalid("partitions must not be empty"));
        }
        for (name, group) in groups {
            validate_name(name)?;
            if !group.is_object() {
                return Err(invalid("each partition must be an object"));
            }
            patterns(&group["include"], true)?;
            patterns(&group["exclude"], false)?;
        }
    } else if layout["mode"] == "custom" {
        return Err(invalid("custom mode requires partitions"));
    }
    for key in ["groupingOverrides", "pathPrefixParts"] {
        if let Some(map) = layout.get(key) {
            for (from, to) in map
                .as_object()
                .ok_or_else(|| invalid("override maps must be objects"))?
            {
                validate_name(from)?;
                validate_name(
                    to.as_str()
                        .ok_or_else(|| invalid("override values must be part names"))?,
                )?;
            }
        }
    }
    if layout
        .get("splitDepth")
        .is_some_and(|d| d.as_u64().is_none_or(|d| d < 1))
    {
        return Err(invalid("splitDepth must be a positive integer"));
    }
    if let Some(sources) = layout.get("sourceFolders") {
        for source in sources
            .as_array()
            .ok_or_else(|| invalid("sourceFolders must be an array"))?
        {
            validate_name(
                source
                    .as_str()
                    .ok_or_else(|| invalid("sourceFolders must contain strings"))?,
            )?;
        }
    }
    Ok(())
}
pub fn load(root: &Path) -> Result<Value> {
    let path = persistence::data_dir(root).join("partition-layout.json");
    if !path.exists() {
        return Ok(Value::Null);
    }
    let value = persistence::read_json(&path)?;
    validate(&value)?;
    Ok(value)
}
pub fn save(root: &Path, layout: &Value) -> Result<()> {
    validate(layout)?;
    let data = persistence::data_dir(root);
    std::fs::create_dir_all(&data)?;
    let staged = tempfile::NamedTempFile::new_in(&data)?;
    persistence::write_json(staged.path(), layout)?;
    staged
        .persist(data.join("partition-layout.json"))
        .map_err(|e| e.error)?;
    Ok(())
}
pub fn changed(root: &Path) -> Result<bool> {
    let path = persistence::data_dir(root).join("meta.json");
    let meta = if path.exists() {
        persistence::read_json(&path)?
    } else {
        Value::Null
    };
    Ok(load(root)? != meta["partitionLayout"])
}
/// Explicit patterns may overlap. Hybrid mode assigns only unmatched files to
/// folder parts. Legacy override maps continue to apply to those folder parts.
pub fn assign(
    root: &Path,
    paths: &[String],
    sources: &[String],
    depth: Option<usize>,
) -> Result<BTreeMap<String, Vec<String>>> {
    let layout = load(root)?;
    assign_with_layout(&layout, paths, sources, depth)
}
pub fn assign_with_layout(
    layout: &Value,
    paths: &[String],
    sources: &[String],
    depth: Option<usize>,
) -> Result<BTreeMap<String, Vec<String>>> {
    if !layout.is_null() {
        validate(layout)?;
    }
    let mut parts = BTreeMap::new();
    let mut unmatched = paths.to_vec();
    if let Some(groups) = layout["partitions"].as_object() {
        let mut matched = std::collections::BTreeSet::new();
        for (name, group) in groups {
            let include = IgnoreFilter::new(&patterns(&group["include"], true)?)?;
            let exclude = IgnoreFilter::new(&patterns(&group["exclude"], false)?)?;
            let files: Vec<_> = paths
                .iter()
                .map(|p| partition::posix(p))
                .filter(|p| include.is_ignored(p) && !exclude.is_ignored(p))
                .collect();
            matched.extend(files.iter().cloned());
            parts.insert(name.clone(), files);
        }
        unmatched.retain(|p| !matched.contains(&partition::posix(p)));
    }
    if layout["mode"] != "custom" {
        let sources = if layout.get("sourceFolders").is_some() {
            crate::strings(&layout["sourceFolders"])
        } else {
            sources.to_vec()
        };
        let depth = layout["splitDepth"].as_u64().map(|d| d as usize).or(depth);
        for (part, files) in partition::partition_files(&unmatched, &sources, depth)? {
            for file in files {
                let prefix = layout["pathPrefixParts"].as_object().and_then(|m| {
                    m.iter()
                        .filter(|(p, _)| file == **p || file.starts_with(&format!("{p}/")))
                        .max_by_key(|(p, _)| p.len())
                        .and_then(|(_, v)| v.as_str())
                });
                let name = prefix
                    .or_else(|| layout["groupingOverrides"][&part].as_str())
                    .unwrap_or(&part);
                parts.entry(name.to_owned()).or_default().push(file);
            }
        }
    }
    for (name, files) in &mut parts {
        validate_name(name)?;
        files.sort();
        files.dedup();
    }
    Ok(parts)
}
/// A changed definition invalidates generated inventories, including during an
/// in-flight batch run. No fallback to stale manual inventories is allowed.
pub fn verify_inventory(root: &Path) -> Result<()> {
    let layout = load(root)?;
    let path = persistence::data_dir(root).join("intermediate/partitions.json");
    let inventory = if path.exists() {
        persistence::read_json(&path)?
    } else {
        Value::Null
    };
    if inventory["partitionLayout"] != layout {
        return Err(Error::Invalid("Partition layout changed; run partition_files again before preparing or publishing parts".into()));
    }
    Ok(())
}
pub fn status(root: &Path) -> Result<Value> {
    Ok(json!({"changed":changed(root)?, "layout":load(root)?}))
}
