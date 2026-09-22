//! Deterministic graph review, separate from permissive persistence repairs.
use crate::{array, strings, tables};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
const FILE_TYPES: &[&str] = &[
    "file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint",
];
const DOMAIN_TYPES: &[&str] = &["domain", "flow", "step"];
fn text(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(b) => if *b { "True" } else { "False" }.into(),
        Value::String(s) => s.clone(),
        _ => v.to_string(),
    }
}
fn repr(v: &Value) -> String {
    match v {
        Value::String(s) => format!("'{s}'"),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        _ => text(v),
    }
}
fn nonempty(v: &Value) -> bool {
    v.as_str().is_some_and(|s| !s.is_empty())
}
fn valid(kind: &str, v: &Value) -> bool {
    tables()["constants"][kind]
        .as_array()
        .is_some_and(|a| a.contains(v))
}
pub fn review_graph(graph: &Value, require_layers: bool) -> Value {
    let (nodes, edges, layers) = (
        array(graph, "nodes"),
        array(graph, "edges"),
        array(graph, "layers"),
    );
    let mut issues = Vec::<String>::new();
    let mut warnings = Vec::<String>::new();
    let domain = nodes
        .iter()
        .any(|n| DOMAIN_TYPES.contains(&n["type"].as_str().unwrap_or("")));
    // Insertion order is diagnostic order, independent of hash randomization.
    let mut positions = serde_json::Map::new();
    for (i, n) in nodes.iter().enumerate() {
        if nonempty(&n["id"]) {
            positions
                .entry(text(&n["id"]))
                .or_insert(json!([]))
                .as_array_mut()
                .unwrap()
                .push(json!(i));
        }
    }
    for (id, pos) in &positions {
        if pos.as_array().unwrap().len() > 1 {
            issues.push(format!(
                "Duplicate node ID '{id}' appears at indices {}",
                repr(pos)
            ));
        }
    }
    let ids: BTreeSet<_> = positions.keys().map(String::as_str).collect();
    for (i, n) in nodes.iter().enumerate() {
        if !n.is_object() {
            issues.push(format!("Node at index {i} is not an object"));
            continue;
        }
        let label = if nonempty(&n["id"]) {
            text(&n["id"])
        } else if nonempty(&n["name"]) {
            text(&n["name"])
        } else {
            format!("index {i}")
        };
        if !nonempty(&n["id"]) {
            issues.push(format!(
                "Node at index {i} ('{label}') missing required 'id'"
            ));
        }
        if !nonempty(&n["type"]) {
            issues.push(format!("Node '{label}' missing required 'type'"));
        } else if !valid("VALID_NODE_TYPES", &n["type"]) {
            issues.push(format!(
                "Node '{label}' has invalid type '{}'",
                text(&n["type"])
            ));
        }
        if !nonempty(&n["name"]) {
            issues.push(format!("Node '{label}' missing required 'name'"));
        }
        if !nonempty(&n["summary"]) {
            issues.push(format!("Node '{label}' missing required 'summary'"));
        } else if n["summary"] == n["name"]
            || n["summary"].as_str() == n["filePath"].as_str().and_then(|s| s.rsplit('/').next())
        {
            warnings.push(format!("Node '{label}' has a generic summary"));
        }
        if !n["tags"].is_array() {
            issues.push(format!("Node '{label}' missing required 'tags' array"));
        }
        if !valid("VALID_COMPLEXITY", &n["complexity"]) {
            issues.push(format!(
                "Node '{label}' has invalid complexity '{}'",
                text(&n["complexity"])
            ));
        }
    }
    let mut degree = BTreeMap::<String, usize>::new();
    for (i, e) in edges.iter().enumerate() {
        if !e.is_object() {
            issues.push(format!("Edge at index {i} is not an object"));
            continue;
        }
        for key in ["source", "target"] {
            if !nonempty(&e[key]) {
                issues.push(format!("Edge at index {i} missing required '{key}'"));
            } else if !ids.contains(e[key].as_str().unwrap()) {
                issues.push(format!(
                    "Edge at index {i} references non-existent {key} node '{}'",
                    text(&e[key])
                ));
            }
        }
        if !valid("VALID_EDGE_TYPES", &e["type"]) {
            issues.push(format!(
                "Edge at index {i} has invalid type '{}'",
                text(&e["type"])
            ));
        }
        if !valid("VALID_DIRECTIONS", &e["direction"]) {
            issues.push(format!(
                "Edge at index {i} has invalid direction '{}'",
                text(&e["direction"])
            ));
        }
        if e["weight"]
            .as_f64()
            .is_none_or(|x| !(0.0..=1.0).contains(&x))
        {
            issues.push(format!(
                "Edge at index {i} has weight outside 0.0-1.0: {}",
                repr(&e["weight"])
            ));
        }
        if let (Some(src), Some(tgt)) = (e["source"].as_str(), e["target"].as_str()) {
            if src == tgt {
                warnings.push(format!("Edge at index {i} is self-referencing ('{src}')"));
            }
            *degree.entry(src.into()).or_default() += 1;
            *degree.entry(tgt.into()).or_default() += 1;
        }
    }
    let mut membership = BTreeMap::<String, Vec<String>>::new();
    for (i, l) in layers.iter().enumerate() {
        if !l.is_object() {
            issues.push(format!("Layer at index {i} is not an object"));
            continue;
        }
        let label = l.get("id").map(text).unwrap_or_else(|| i.to_string());
        if array(l, "nodeIds").is_empty() {
            issues.push(format!("Layer '{label}' has an empty nodeIds array"));
            continue;
        }
        for id in array(l, "nodeIds") {
            if !ids.contains(id.as_str().unwrap_or("")) {
                issues.push(format!(
                    "Layer '{label}' references non-existent node '{}'",
                    text(id)
                ));
            } else {
                membership.entry(text(id)).or_default().push(label.clone());
            }
        }
    }
    if nodes.is_empty() {
        issues.push("Graph has zero nodes".into());
    }
    if edges.is_empty() {
        issues.push("Graph has zero edges".into());
    }
    if layers.is_empty() {
        if domain {
            warnings.push("Domain graph has zero layers (relaxed to warning)".into());
        } else if !require_layers {
            warnings.push(
                "Assembled graph has zero layers (pre-layer stage — relaxed to warning)".into(),
            );
        } else {
            issues.push("Graph has zero layers".into());
        }
    }
    if require_layers && !(domain && layers.is_empty()) {
        for n in nodes {
            if FILE_TYPES.contains(&n["type"].as_str().unwrap_or("")) && nonempty(&n["id"]) {
                let id = text(&n["id"]);
                let appearances = membership.get(&id).cloned().unwrap_or_default();
                if appearances.is_empty() {
                    issues.push(format!("File-level node '{id}' is missing from all layers"));
                } else if appearances.len() > 1 {
                    issues.push(format!(
                        "File-level node '{id}' appears in multiple layers: {}",
                        repr(&json!(appearances))
                    ));
                }
            }
        }
    }
    for n in nodes {
        if nonempty(&n["id"]) && degree.get(&text(&n["id"])).copied().unwrap_or(0) == 0 {
            warnings.push(format!(
                "Orphan node '{}' has no connecting edges",
                text(&n["id"])
            ));
        }
    }
    for n in nodes {
        let t = n["type"].as_str().unwrap_or("");
        let id = text(&n["id"]);
        let expected: &[&str] = match t {
            "document" => &["documents"],
            "service" => &["deploys", "depends_on"],
            "pipeline" => &["triggers"],
            "table" => &["migrates", "defines_schema"],
            "schema" => &["defines_schema"],
            "domain" => &["contains_flow"],
            "flow" => &["flow_step"],
            _ => &[],
        };
        if !expected.is_empty()
            && nonempty(&n["id"])
            && !edges.iter().any(|e| {
                e["source"].is_string()
                    && (e["source"] == n["id"] || e["target"] == n["id"])
                    && expected.contains(&e["type"].as_str().unwrap_or(""))
            })
        {
            let label = format!("{}{}", t[..1].to_uppercase(), &t[1..]);
            warnings.push(format!(
                "{label} node '{id}' has no {} edges",
                expected.join(" or ")
            ));
        }
    }
    for n in nodes {
        if let (Some(id), Some(t)) = (n["id"].as_str(), n["type"].as_str())
            && let Some((prefix, _)) = id.split_once(':')
            && prefix != t
        {
            warnings.push(format!(
                "Node '{id}' type '{t}' does not match ID prefix '{prefix}:'"
            ));
        }
    }
    fn counts(items: &[Value]) -> Value {
        let mut c = json!({});
        for i in items {
            if let Some(t) = i["type"].as_str().filter(|t| !t.is_empty()) {
                c[t] = json!(c[t].as_u64().unwrap_or(0) + 1);
            }
        }
        c
    }
    json!({"scriptCompleted":true,"issues":issues,"warnings":warnings,"stats":{"totalNodes":nodes.len(),"totalEdges":edges.len(),"totalLayers":layers.len(),"nodeTypes":counts(nodes),"edgeTypes":counts(edges)}})
}
pub fn add_scan_coverage(review: &mut Value, graph: &Value, scanned: &[String]) {
    let covered: BTreeSet<String> = array(graph, "nodes")
        .iter()
        .filter_map(|n| {
            n["filePath"]
                .as_str()
                .filter(|p| !p.is_empty())
                .map(str::to_owned)
                .or_else(|| {
                    let mut parts = n["id"].as_str()?.split(':');
                    let prefix = parts.next()?;
                    if FILE_TYPES.contains(&prefix) || ["function", "class"].contains(&prefix) {
                        parts.next().map(str::to_owned)
                    } else {
                        None
                    }
                })
        })
        .filter(|p| !p.is_empty())
        .collect();
    let scanned: BTreeSet<_> = scanned.iter().cloned().collect();
    let missing: Vec<_> = scanned.difference(&covered).collect();
    let extra: Vec<_> = covered.difference(&scanned).collect();
    let warnings = review["warnings"].as_array_mut().unwrap();
    for p in missing.iter().take(50) {
        warnings.push(json!(format!(
            "Scanned file '{p}' has no corresponding node in the graph"
        )));
    }
    if missing.len() > 50 {
        warnings.push(json!(format!(
            "... and {} more scanned files with no node",
            missing.len() - 50
        )));
    }
    for p in extra.iter().take(50) {
        warnings.push(json!(format!(
            "Node references file '{p}' not present in the scan inventory"
        )));
    }
    if extra.len() > 50 {
        warnings.push(json!(format!(
            "... and {} more nodes referencing unknown files",
            extra.len() - 50
        )));
    }
    review["stats"]["coverage"] = json!({"scannedFiles":scanned.len(),"filesWithNodes":scanned.intersection(&covered).count(),"missingFileNodes":missing.len(),"unknownFileNodes":extra.len()});
}
pub fn review_domain_graph(graph: &Value) -> Value {
    let mut review = review_graph(graph, true);
    let mut issues = strings(&review["issues"]);
    let nodes: Vec<_> = array(graph, "nodes")
        .iter()
        .filter(|n| n.is_object())
        .collect();
    let edges: Vec<_> = array(graph, "edges")
        .iter()
        .filter(|n| n.is_object())
        .collect();
    let types: BTreeMap<_, _> = nodes
        .iter()
        .filter_map(|n| {
            n["id"]
                .as_str()
                .map(|id| (id, n["type"].as_str().unwrap_or("")))
        })
        .collect();
    if !nodes.iter().any(|n| n["type"] == "domain") {
        issues.push("Domain graph has zero 'domain' nodes".into());
    }
    for n in &nodes {
        if !DOMAIN_TYPES.contains(&n["type"].as_str().unwrap_or("")) {
            issues.push(format!(
                "Node '{}' has non-domain type '{}' (allowed: domain, flow, step)",
                text(&n["id"]),
                text(&n["type"])
            ));
        }
    }
    for (i, e) in edges.iter().enumerate() {
        if !["contains_flow", "flow_step", "cross_domain"]
            .contains(&e["type"].as_str().unwrap_or(""))
        {
            issues.push(format!("Edge at index {i} has non-domain type '{}' (allowed: contains_flow, flow_step, cross_domain)",text(&e["type"])));
        }
    }
    let mut flows = BTreeSet::new();
    let mut steps = BTreeSet::new();
    let mut weights = serde_json::Map::new();
    for e in &edges {
        let src = text(&e["source"]);
        let tgt = text(&e["target"]);
        let st = types.get(src.as_str()).copied().unwrap_or("");
        let tt = types.get(tgt.as_str()).copied().unwrap_or("");
        match e["type"].as_str().unwrap_or("") {
            "contains_flow" => {
                if st != "domain" {
                    issues.push(format!(
                        "contains_flow edge {src} → {tgt} must originate from a domain node"
                    ));
                }
                if tt == "flow" {
                    flows.insert(tgt);
                }
            }
            "flow_step" => {
                if st != "flow" {
                    issues.push(format!(
                        "flow_step edge {src} → {tgt} must originate from a flow node"
                    ));
                }
                if tt == "step" {
                    steps.insert(tgt);
                }
                weights
                    .entry(src)
                    .or_insert(json!([]))
                    .as_array_mut()
                    .unwrap()
                    .push(e["weight"].clone());
            }
            "cross_domain" if (st != "domain" || tt != "domain") => {
                issues.push(format!(
                    "cross_domain edge {src} → {tgt} must connect two domain nodes"
                ));
            }
            _ => {}
        }
    }
    for n in &nodes {
        let id = text(&n["id"]);
        if n["type"] == "flow" && !flows.contains(&id) {
            issues.push(format!(
                "Flow '{id}' is not connected to any domain via a contains_flow edge"
            ));
        }
        if n["type"] == "step" && !steps.contains(&id) {
            issues.push(format!(
                "Step '{id}' is not connected to any flow via a flow_step edge"
            ));
        }
    }
    if !array(graph, "layers").is_empty() {
        issues.push(format!(
            "Domain graph must have empty layers (found {} layer(s))",
            array(graph, "layers").len()
        ));
    }
    for (id, ww) in weights {
        let w: Vec<_> = ww
            .as_array()
            .unwrap()
            .iter()
            .filter_map(Value::as_f64)
            .collect();
        if w.windows(2).any(|v| v[1] < v[0]) {
            issues.push(format!(
                "Flow '{id}' has non-monotonic flow_step weights: {}",
                repr(&ww)
            ));
        }
    }
    if let Err(e) = crate::schemas::validate("domain-graph", graph) {
        issues.push(format!("schema validation: {e}"));
    }
    review["issues"] = json!(issues);
    review
}
