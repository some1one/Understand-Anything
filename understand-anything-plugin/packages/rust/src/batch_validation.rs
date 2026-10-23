//! Validation and partitioning of supplied extraction output and graph drafts.
use crate::{array, schemas, strings};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn repr_list(values: &[String]) -> String {
    format!(
        "[{}]",
        values
            .iter()
            .map(|s| format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'")))
            .collect::<Vec<_>>()
            .join(", ")
    )
}
pub fn graph_fragment(data: &Value) -> Value {
    json!({"nodes":data.get("nodes").cloned().unwrap_or_else(||json!([])),"edges":data.get("edges").cloned().unwrap_or_else(||json!([]))})
}
pub fn validate_draft(context: &Value, seed: &Value, draft: &Value) -> Vec<String> {
    if let Err(e) = schemas::validate("graph-fragment", draft) {
        return vec![format!("draft schema validation failed: {e}")];
    }
    let nodes = array(draft, "nodes");
    let edges = array(draft, "edges");
    let node_ids: BTreeSet<_> = nodes.iter().map(|n| s(n, "id")).collect();
    let tags: BTreeMap<_, BTreeSet<_>> = nodes
        .iter()
        .map(|n| (s(n, "id"), strings(&n["tags"]).into_iter().collect()))
        .collect();
    let keys: BTreeSet<_> = edges
        .iter()
        .map(|e| (s(e, "source"), s(e, "target"), s(e, "type")))
        .collect();
    let mut issues = vec![];
    for n in array(seed, "nodes") {
        let id = s(n, "id");
        if !node_ids.contains(id) {
            issues.push(format!("seeded node '{id}' is missing from the draft"));
            continue;
        }
        let required: BTreeSet<_> = strings(&n["tags"]).into_iter().collect();
        let missing: Vec<_> = required.difference(&tags[id]).cloned().collect();
        if !missing.is_empty() {
            issues.push(format!(
                "seeded node '{id}' is missing required tag(s): {}",
                repr_list(&missing)
            ));
        }
    }
    for e in array(seed, "edges") {
        let (src, tgt, typ) = (s(e, "source"), s(e, "target"), s(e, "type"));
        if !keys.contains(&(src, tgt, typ)) {
            issues.push(format!(
                "seeded {typ} edge {src} → {tgt} is missing from the draft"
            ));
        }
    }
    let mut required = BTreeSet::new();
    let mut batch_ids = BTreeSet::new();
    let mut allowed: BTreeSet<String> = node_ids.iter().map(|s| (*s).into()).collect();
    if let Some(imports) = context["batchImportData"].as_object() {
        for (src, targets) in imports {
            batch_ids.insert(format!("file:{src}"));
            for target in strings(targets).into_iter().filter(|s| !s.is_empty()) {
                allowed.insert(format!("file:{target}"));
                if target != *src {
                    required.insert((format!("file:{src}"), format!("file:{target}")));
                }
            }
        }
    }
    let present: BTreeSet<_> = edges
        .iter()
        .filter(|e| e["type"] == "imports")
        .map(|e| (s(e, "source").to_owned(), s(e, "target").to_owned()))
        .collect();
    for (src, tgt) in required.difference(&present) {
        issues.push(format!("missing imports edge {src} → {tgt}"));
    }
    for (src, tgt) in &present {
        if batch_ids.contains(src) && !required.contains(&(src.clone(), tgt.clone())) {
            issues.push(format!(
                "spurious imports edge {src} → {tgt} not present in batchImportData"
            ));
        }
    }
    if let Some(neighbors) = context["neighborMap"].as_object() {
        for list in neighbors.values() {
            if let Some(list) = list.as_array() {
                for n in list {
                    if let Some(path) = n["path"].as_str() {
                        allowed.insert(format!("file:{path}"));
                        for sym in strings(&n["symbols"]).iter().filter(|s| !s.is_empty()) {
                            allowed.insert(format!("function:{path}:{sym}"));
                            allowed.insert(format!("class:{path}:{sym}"));
                        }
                    }
                }
            }
        }
    }
    for (i, e) in edges.iter().enumerate() {
        let (src, tgt) = (s(e, "source"), s(e, "target"));
        if !node_ids.contains(src) {
            issues.push(format!(
                "edge[{i}] {src} → {tgt}: source is not a node defined in this batch"
            ));
        }
        if !allowed.contains(tgt) {
            issues.push(format!("edge[{i}] {src} → {tgt}: target is neither in-batch nor an allowed cross-batch reference (import target or neighborMap symbol)"));
        }
    }
    issues
}
pub fn split_into_parts(nodes: &[Value], edges: &[Value], batch_files: &[String]) -> Vec<Value> {
    if nodes.len() <= 60 && edges.len() <= 120 {
        return vec![json!({"nodes":nodes,"edges":edges})];
    }
    let count = nodes
        .len()
        .div_ceil(60)
        .max(edges.len().div_ceil(120))
        .max(1);
    let mut files = batch_files.to_vec();
    files.sort();
    let per = files.len().div_ceil(count);
    let file_part: BTreeMap<_, _> = files
        .iter()
        .enumerate()
        .map(|(i, p)| (p.as_str(), i.checked_div(per).unwrap_or(0)))
        .collect();
    let mut node_part = BTreeMap::new();
    let mut out: Vec<Value> = (0..count).map(|_| json!({"nodes":[],"edges":[]})).collect();
    for n in nodes {
        let path = n["filePath"]
            .as_str()
            .filter(|p| !p.is_empty())
            .or_else(|| s(n, "id").split(':').nth(1))
            .unwrap_or("");
        let p = file_part.get(path).copied().unwrap_or(0).min(count - 1);
        out[p]["nodes"].as_array_mut().unwrap().push(n.clone());
        if !s(n, "id").is_empty() {
            node_part.insert(s(n, "id"), p);
        }
    }
    for e in edges {
        let p = node_part.get(s(e, "source")).copied().unwrap_or(0);
        out[p]["edges"].as_array_mut().unwrap().push(e.clone());
    }
    out
}
pub fn check_structure_output(input: &Value, results: &Value) -> Vec<String> {
    if let Err(e) = schemas::validate("structure-output", results) {
        return vec![format!("schema validation failed: {e}")];
    }
    let rows = array(results, "results");
    let mut issues = vec![];
    for failure in array(results, "filesUnreadable") {
        issues.push(format!(
            "batch file '{}' could not be read ({}); repair the input before analysis",
            s(failure, "path"),
            s(failure, "code")
        ));
    }
    if results["filesAnalyzed"].as_u64() != Some(rows.len() as u64) {
        issues.push(format!(
            "filesAnalyzed ({}) does not match the number of results ({})",
            results["filesAnalyzed"],
            rows.len()
        ));
    }
    let mut seen = BTreeSet::new();
    for r in rows {
        let path = s(r, "path");
        if !seen.insert(path.to_owned()) {
            issues.push(format!("duplicate result for path '{path}'"));
        }
    }
    for r in rows {
        let path = s(r, "path");
        if let Some(metrics) = r["metrics"].as_object() {
            for (k, v) in metrics {
                if v.as_u64().is_none() {
                    issues.push(format!("result for '{path}' has malformed metric '{k}'={v} (expected a non-negative integer)"));
                }
            }
        } else {
            issues.push(format!("result for '{path}' has non-object metrics"));
        }
    }
    seen.extend(strings(&results["filesSkipped"]));
    for file in array(input, "batchFiles") {
        if !file.is_object() {
            continue;
        }
        let path = s(file, "path");
        if !seen.contains(path) {
            issues.push(format!(
                "batch file '{path}' is missing from results and was not skipped"
            ));
        }
    }
    issues
}
pub fn check_layers(input: &Value, layers: &Value) -> Vec<String> {
    let mut issues = vec![];
    if let Err(e) = schemas::validate("layers", layers) {
        issues.push(format!("schema: {e}"));
        if !layers.is_array() {
            return issues;
        }
    }
    let layers = layers.as_array().unwrap();
    if !(3..=10).contains(&layers.len()) {
        issues.push(format!(
            "layer count {} is outside the allowed range 3..10",
            layers.len()
        ));
    }
    let mut ids = BTreeMap::new();
    let mut assigned = BTreeMap::new();
    for layer in layers {
        *ids.entry(s(layer, "id").to_owned()).or_insert(0usize) += 1;
        for id in strings(&layer["nodeIds"]) {
            *assigned.entry(id).or_insert(0usize) += 1;
        }
    }
    let duplicate_layers: Vec<_> = ids
        .into_iter()
        .filter(|(_, n)| *n > 1)
        .map(|(id, _)| id)
        .collect();
    if !duplicate_layers.is_empty() {
        issues.push(format!(
            "duplicate layer ids: {}",
            repr_list(&duplicate_layers)
        ));
    }
    let input_ids: BTreeSet<_> = array(input, "fileNodes")
        .iter()
        .map(|n| s(n, "id").to_owned())
        .collect();
    let assigned_ids: BTreeSet<_> = assigned.keys().cloned().collect();
    let missing: Vec<_> = input_ids.difference(&assigned_ids).cloned().collect();
    let invented: Vec<_> = assigned_ids.difference(&input_ids).cloned().collect();
    let duplicated: Vec<_> = assigned
        .into_iter()
        .filter(|(_, n)| *n > 1)
        .map(|(id, _)| id)
        .collect();
    for (values, label) in [
        (missing, "input node(s) not assigned to any layer"),
        (invented, "node id(s) not present in input (invented)"),
        (duplicated, "node id(s) assigned to multiple layers"),
    ] {
        if !values.is_empty() {
            issues.push(format!(
                "{} {label}: {}",
                values.len(),
                repr_list(&values[..values.len().min(20)])
            ));
        }
    }
    issues
}
