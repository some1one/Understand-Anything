//! Assembly of deterministic scanning output and project narrative.
use crate::{Error, Result, array, strings};
use serde_json::{Value, json};
use std::{collections::BTreeSet, path::Path};
pub fn assemble_scan_result(
    scan: &Value,
    import_output: &Value,
    narrative: &Value,
    root: &Path,
) -> Result<Value> {
    let files = scan["files"]
        .as_array()
        .ok_or_else(|| Error::Invalid("scan output missing 'files' array".into()))?;
    let total = scan["totalFiles"]
        .as_u64()
        .ok_or_else(|| Error::Invalid("scan output missing integer 'totalFiles'".into()))?;
    if total != files.len() as u64 {
        return Err(Error::Invalid(format!(
            "scan output totalFiles ({total}) != len(files) ({})",
            files.len()
        )));
    }
    let filtered = scan["filteredByIgnore"]
        .as_u64()
        .ok_or_else(|| Error::Invalid("scan output missing integer 'filteredByIgnore'".into()))?;
    let complexity = scan["estimatedComplexity"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| Error::Invalid("scan output missing 'estimatedComplexity'".into()))?;
    let imports = import_output["importMap"]
        .as_object()
        .ok_or_else(|| Error::Invalid("import-map output missing 'importMap' object".into()))?;
    let paths: BTreeSet<_> = files.iter().filter_map(|f| f["path"].as_str()).collect();
    let missing: Vec<_> = paths
        .iter()
        .filter(|p| !imports.contains_key(**p))
        .copied()
        .collect();
    if !missing.is_empty() {
        return Err(Error::Invalid(format!(
            "importMap is missing entries for {} scanned file(s) (e.g. {}) — scan and import-map outputs are out of sync",
            missing.len(),
            missing
                .iter()
                .take(5)
                .copied()
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }
    let name = narrative["name"].as_str().unwrap_or("").trim();
    let name = if name.is_empty() {
        root.file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("unnamed-project")
    } else {
        name
    };
    let mut description = narrative["description"]
        .as_str()
        .unwrap_or("")
        .trim()
        .to_owned();
    if description.is_empty() {
        description = "No description available".into();
    }
    let note = " Note: this project has over 100 source files; consider scoping analysis to a subdirectory for faster results.";
    if total > 100 && !description.contains(note.trim()) {
        description.push_str(note);
    }
    let languages = if array(narrative, "languages").is_empty() {
        let mut keys = scan["stats"]["byLanguage"]
            .as_object()
            .map(|m| m.keys().cloned().collect::<Vec<_>>())
            .unwrap_or_default();
        keys.sort();
        keys
    } else {
        strings(&narrative["languages"])
    };
    let mut result = json!({"name":name,"description":description,"languages":languages,"frameworks":array(narrative,"frameworks"),"files":files,"totalFiles":total,"filteredByIgnore":filtered,"estimatedComplexity":complexity,"importMap":imports});
    if let Some(patterns) = scan.get("excludePatterns") {
        if !patterns.as_array().is_some_and(|patterns| patterns.iter().all(Value::is_string)) {
            return Err(Error::Invalid("scan excludePatterns must be an array of strings".into()));
        }
        result["excludePatterns"] = patterns.clone();
    }
    Ok(result)
}
pub fn build_part_graph(
    assembled: &Value,
    part: &str,
    known_paths: &BTreeSet<String>,
    scan: &Value,
    commit: &str,
) -> Value {
    let stubbed = crate::merge::add_boundary_stubs(
        &crate::batch_validation::graph_fragment(assembled),
        known_paths,
    );
    json!({"version":assembled.get("version").cloned().unwrap_or_else(||json!("1.0.0")),"part":part,"project":{"name":scan["name"].as_str().unwrap_or(""),"description":scan["description"].as_str().unwrap_or(""),"languages":array(scan,"languages"),"frameworks":array(scan,"frameworks"),"analyzedAt":crate::now_iso(),"gitCommitHash":commit},"nodes":stubbed["nodes"],"edges":stubbed["edges"],"layers":[]})
}
