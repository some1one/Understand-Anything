//! Bounded, graph-ordered chat context; no runtime downloads or relevance ranking.
use crate::{
    Result, array,
    query_terms::{Lexicon, Words},
};
use serde_json::{Value, json};
use std::collections::BTreeSet;
pub const MAX_PAYLOAD_BYTES: usize = 32 * 1024;
pub fn serialize(value: &Value) -> Result<String> {
    Ok(serde_json::to_string_pretty(value)? + "\n")
}
fn clipped(value: &str, limit: usize) -> String {
    if value.len() <= limit {
        return value.to_owned();
    }
    let mut end = limit.saturating_sub(3);
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}…", &value[..end])
}
fn compact(value: &Value, depth: usize) -> Value {
    match value {
        Value::String(s) => json!(clipped(s, 2048)),
        Value::Array(_) | Value::Object(_) if depth >= 4 => Value::Null,
        Value::Array(items) => Value::Array(
            items
                .iter()
                .take(16)
                .map(|v| compact(v, depth + 1))
                .collect(),
        ),
        Value::Object(items) => Value::Object(
            items
                .iter()
                .take(32)
                .map(|(k, v)| (clipped(k, 256), compact(v, depth + 1)))
                .collect(),
        ),
        _ => value.clone(),
    }
}
fn count_key(key: &str) -> String {
    format!("omitted{}{}", key[..1].to_uppercase(), &key[1..])
}
fn append(payload: &mut Value, key: &str, value: &Value, budget: usize) -> Result<bool> {
    let mut item = compact(value, 0);
    for identity in ["id", "filePath", "source", "target", "nodeIds"] {
        if let Some(v) = value.get(identity) {
            item[identity] = v.clone();
        }
    }
    let shortened = item != *value;
    payload[key].as_array_mut().unwrap().push(item);
    if serialize(payload)?.len() > budget {
        payload[key].as_array_mut().unwrap().pop();
        return Ok(false);
    }
    let count = count_key(key);
    payload["truncation"][&count] = json!(payload["truncation"][&count].as_u64().unwrap() - 1);
    if shortened {
        payload["truncation"]["textShortened"] = json!(true);
    }
    Ok(true)
}
fn ids(nodes: &[Value]) -> BTreeSet<String> {
    nodes
        .iter()
        .filter_map(|n| {
            n["id"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_owned)
        })
        .collect()
}
pub fn build_payload(graph: &Value, query: &str, cached: &Words) -> Result<Value> {
    let lexicon = Lexicon::load()?;
    let matched = lexicon.matching_nodes(graph, query, cached);
    let original = graph.get("project").cloned().unwrap_or(json!({}));
    let mut project = compact(&original, 0);
    if serialize(&json!({"project":project}))?.len() > 4096 {
        project = json!({"name":clipped(original["name"].as_str().unwrap_or(""),1024),
            "description":clipped(original["description"].as_str().unwrap_or(""),1024)});
    }
    let mut payload = json!({"project":project,"query":clipped(query,2048),
        "matchedNodes":[],"connectedNodes":[],"edges":[],"layers":[],
        "truncation":{"maxBytes":MAX_PAYLOAD_BYTES,"omittedMatchedNodes":matched.len(),
            "omittedConnectedNodes":0,"omittedEdges":0,"omittedLayers":0,
            "textShortened":project!=original || clipped(query,2048)!=query}});
    for node in matched.iter().take(25) {
        append(&mut payload, "matchedNodes", node, MAX_PAYLOAD_BYTES - 4096)?;
    }
    let matched_ids = ids(array(&payload, "matchedNodes"));
    let edges: Vec<_> = array(graph, "edges")
        .iter()
        .filter(|e| {
            ["source", "target"]
                .iter()
                .any(|k| e[k].as_str().is_some_and(|id| matched_ids.contains(id)))
        })
        .collect();
    let neighbors: BTreeSet<_> = edges
        .iter()
        .flat_map(|e| [e["source"].as_str(), e["target"].as_str()])
        .flatten()
        .collect();
    let connected: Vec<_> = array(graph, "nodes")
        .iter()
        .filter(|n| {
            n["id"]
                .as_str()
                .is_some_and(|id| neighbors.contains(id) && !matched_ids.contains(id))
        })
        .collect();
    payload["truncation"]["omittedConnectedNodes"] = json!(connected.len());
    payload["truncation"]["omittedEdges"] = json!(edges.len());
    for node in connected.iter().take(50) {
        append(
            &mut payload,
            "connectedNodes",
            node,
            MAX_PAYLOAD_BYTES - 4096,
        )?;
    }
    let mut selected = matched_ids;
    selected.extend(ids(array(&payload, "connectedNodes")));
    for edge in edges.iter().take(100) {
        if ["source", "target"]
            .iter()
            .all(|k| edge[k].as_str().is_some_and(|id| selected.contains(id)))
        {
            append(&mut payload, "edges", edge, MAX_PAYLOAD_BYTES)?;
        }
    }
    let layers: Vec<_> = array(graph, "layers")
        .iter()
        .filter(|l| {
            array(l, "nodeIds")
                .iter()
                .any(|id| id.as_str().is_some_and(|id| selected.contains(id)))
        })
        .collect();
    payload["truncation"]["omittedLayers"] = json!(layers.len());
    for layer in layers {
        let mut item = json!({});
        for key in ["id", "name", "description"] {
            if let Some(v) = layer.get(key) {
                item[key] = v.clone();
            }
        }
        item["nodeIds"] = json!(
            array(layer, "nodeIds")
                .iter()
                .filter(|v| v.as_str().is_some_and(|id| selected.contains(id)))
                .collect::<Vec<_>>()
        );
        item["totalMembers"] = json!(array(layer, "nodeIds").len());
        append(&mut payload, "layers", &item, MAX_PAYLOAD_BYTES)?;
    }
    while serialize(&payload)?.len() > MAX_PAYLOAD_BYTES {
        let key = ["layers", "edges"]
            .into_iter()
            .find(|k| !array(&payload, k).is_empty())
            .ok_or_else(|| crate::Error::Invalid("query metadata exceeds payload budget".into()))?;
        payload[key].as_array_mut().unwrap().pop();
        let count = count_key(key);
        payload["truncation"][&count] = json!(payload["truncation"][&count].as_u64().unwrap() + 1);
    }
    Ok(payload)
}
