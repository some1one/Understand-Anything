//! Partition boundary stubs and graph merging, including real-node precedence.
use crate::{Result, array, persistence, strings, tables};
use serde_json::{Map, Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};
fn text<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
pub fn parse_node_id(id: &str) -> Option<(String, String, String)> {
    let parts: Vec<_> = id.split(':').collect();
    if parts.len() < 2 {
        return None;
    }
    let path = parts[1..parts.len() - usize::from(parts.len() > 2)].join(":");
    let name = if parts.len() == 2 {
        path.rsplit('/').next().unwrap_or("").to_owned()
    } else {
        parts.last().unwrap().to_string()
    };
    Some((parts[0].into(), path, name))
}
pub fn add_boundary_stubs(graph: &Value, known: &BTreeSet<String>) -> Value {
    let mut nodes = array(graph, "nodes").to_vec();
    let mut ids: BTreeSet<String> = nodes
        .iter()
        .filter_map(|n| n["id"].as_str().map(str::to_owned))
        .collect();
    for edge in array(graph, "edges") {
        for endpoint in ["source", "target"] {
            let id = text(edge, endpoint);
            if id.is_empty() || ids.contains(id) {
                continue;
            }
            if let Some((typ, path, name)) = parse_node_id(id)
                && !path.is_empty()
                && known.contains(&path)
            {
                let valid = [
                    "file", "function", "class", "module", "concept", "config", "document",
                    "service", "table", "endpoint", "pipeline", "schema", "resource", "domain",
                    "flow", "step",
                ];
                let typ = if valid.contains(&typ.as_str()) {
                    typ.as_str()
                } else {
                    "file"
                };
                nodes.push(json!({"id":id,"type":typ,"name":if name.is_empty(){id}else{&name},"summary":"External reference — defined in another part, not analyzed here.","tags":[],"complexity":"simple","filePath":path,"stub":true}));
                ids.insert(id.into());
            }
        }
    }
    let mut out = graph.clone();
    out["nodes"] = json!(nodes);
    out
}
fn number(v: &Value) -> f64 {
    v.as_f64()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
        .unwrap_or(0.)
}
pub fn merge_graphs(graphs: &[Value]) -> (Value, Vec<String>) {
    let mut nodes = Map::new();
    let mut edges: Vec<Value> = vec![];
    let mut edge_index: BTreeMap<(String, String, String), usize> = BTreeMap::new();
    let mut layers = Map::new();
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut unfixable = vec![];
    let mut edge_dupes = 0;
    for graph in graphs {
        for node in array(graph, "nodes") {
            let id = text(node, "id");
            if id.is_empty() {
                unfixable.push(format!(
                    "Node with no 'id' (name={}, type={})",
                    node["name"].as_str().unwrap_or("?"),
                    node["type"].as_str().unwrap_or("?")
                ));
                continue;
            }
            if let Some(existing) = nodes.get(id) {
                let old = existing["stub"].as_bool().unwrap_or(false);
                let new = node["stub"].as_bool().unwrap_or(false);
                if !old && new {
                    continue;
                }
                if old == new {
                    *counts
                        .entry(node["type"].as_str().unwrap_or("?").into())
                        .or_default() += 1;
                }
            }
            nodes.insert(id.into(), node.clone());
        }
        for edge in array(graph, "edges") {
            let key = (
                text(edge, "source").to_owned(),
                text(edge, "target").to_owned(),
                text(edge, "type").to_owned(),
            );
            if let Some(i) = edge_index.get(&key).copied() {
                edge_dupes += 1;
                if number(&edge["weight"]) > number(&edges[i]["weight"]) {
                    edges[i] = edge.clone();
                }
            } else {
                edge_index.insert(key, edges.len());
                edges.push(edge.clone());
            }
        }
        for layer in array(graph, "layers") {
            let id = text(layer, "id");
            if let Some(old) = layers.get_mut(id) {
                let union: BTreeSet<_> = strings(&old["nodeIds"])
                    .into_iter()
                    .chain(strings(&layer["nodeIds"]))
                    .collect();
                old["nodeIds"] = json!(union);
            } else {
                layers.insert(id.into(), layer.clone());
            }
        }
    }
    edges.retain(|e| {
        let src = text(e, "source");
        let tgt = text(e, "target");
        let mut missing = vec![];
        if !nodes.contains_key(src) {
            missing.push(format!("source '{src}'"));
        }
        if !nodes.contains_key(tgt) {
            missing.push(format!("target '{tgt}'"));
        }
        if !missing.is_empty() {
            unfixable.push(format!(
                "Edge {src} → {tgt} ({}): dropped, missing {}",
                e["type"].as_str().unwrap_or("?"),
                missing.join(", ")
            ));
            false
        } else {
            true
        }
    });
    let mut dropped = 0;
    for l in layers.values_mut() {
        let all = strings(&l["nodeIds"]);
        let kept: Vec<_> = all
            .iter()
            .filter(|id| nodes.contains_key(*id))
            .cloned()
            .collect();
        dropped += all.len() - kept.len();
        l["nodeIds"] = json!(kept);
    }
    let mut languages = vec![];
    let mut frameworks = vec![];
    let mut descriptions = vec![];
    let mut name = String::new();
    let mut at = String::new();
    let mut hash = String::new();
    for graph in graphs {
        let p = &graph["project"];
        if !text(p, "name").is_empty() {
            name = text(p, "name").into();
        }
        for (target, key) in [
            (&mut languages, "languages"),
            (&mut frameworks, "frameworks"),
        ] {
            for v in strings(&p[key]) {
                if !target.contains(&v) {
                    target.push(v);
                }
            }
        }
        let desc = text(p, "description").to_owned();
        if !desc.is_empty() && !descriptions.contains(&desc) {
            descriptions.push(desc);
        }
        if text(p, "analyzedAt") > at.as_str() {
            at = text(p, "analyzedAt").into();
            if let Some(v) = p["gitCommitHash"].as_str() {
                hash = v.into();
            }
        }
    }
    let mut report = vec![format!(
        "Input: {} nodes, {} edges (from {} graphs)",
        graphs
            .iter()
            .map(|g| array(g, "nodes").len())
            .sum::<usize>(),
        graphs
            .iter()
            .map(|g| array(g, "edges").len())
            .sum::<usize>(),
        graphs.len()
    )];
    let total = counts.values().sum::<usize>() + edge_dupes + dropped;
    if total > 0 {
        report.push(String::new());
        report.push(format!("Fixed ({total} corrections):"));
        let mut counts: Vec<_> = counts.into_iter().collect();
        counts.sort_by_key(|(_, count)| std::cmp::Reverse(*count));
        for (typ, count) in counts {
            report.push(format!(
                "  {count:>4} × duplicate '{typ}' nodes removed (kept later)"
            ));
        }
        if edge_dupes > 0 {
            report.push(format!(
                "  {edge_dupes:>4} × duplicate edges removed (kept higher weight)"
            ));
        }
        if dropped > 0 {
            report.push(format!(
                "  {dropped:>4} × dangling layer nodeId refs removed"
            ));
        }
    }
    if !unfixable.is_empty() {
        report.push(String::new());
        report.push(format!(
            "Could not fix ({} issues — needs agent review):",
            unfixable.len()
        ));
        report.extend(unfixable.into_iter().map(|s| format!("  - {s}")));
    }
    report.push(String::new());
    report.push(format!(
        "Output: {} nodes, {} edges, {} layers",
        nodes.len(),
        edges.len(),
        layers.len()
    ));
    (
        json!({"version":"1.0.0","project":{"name":name,"languages":languages,"frameworks":frameworks,"description":descriptions.join(" | "),"analyzedAt":at,"gitCommitHash":hash},"nodes":nodes.into_values().collect::<Vec<_>>(),"edges":edges,"layers":layers.into_values().collect::<Vec<_>>()}),
        report,
    )
}
pub fn select_partition_graphs(root: &Path) -> Vec<PathBuf> {
    let dir = root.join(".understand-anything");
    let mut files = vec![];
    for (path, partitions) in [(&dir, false), (&dir.join("partitions"), true)] {
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                let p = entry.path();
                let name = entry.file_name().to_string_lossy().into_owned();
                if (partitions && name.ends_with(".knowledge-graph.json"))
                    || (!partitions
                        && name.contains("knowledge-graph")
                        && name.ends_with(".json")
                        && name != "knowledge-graph.json")
                {
                    files.push(p);
                }
            }
        }
    }
    let included = strings(&persistence::load_config(root)["includedParts"]);
    if !included.is_empty() {
        files.retain(|p| {
            persistence::read_json(p)
                .ok()
                .and_then(|g| g["part"].as_str().map(str::to_owned))
                .is_none_or(|part| included.contains(&part))
        });
    }
    files.sort();
    files.dedup();
    files
}
pub fn load_graph(path: &Path) -> Result<Value> {
    let g = persistence::read_json(path)?;
    if !g["nodes"].is_array() || !g["edges"].is_array() {
        return Err(crate::Error::Invalid("missing nodes or edges array".into()));
    }
    Ok(g)
}
/// Valid taxonomy exported for consumers alongside permissive wire values.
pub fn valid_node_types() -> Vec<String> {
    strings(&tables()["constants"]["VALID_NODE_TYPES"])
}
