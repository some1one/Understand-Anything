//! Repair-oriented graph loading; strict contracts live in `schemas`.
use crate::{array, tables};
use serde_json::{Value, json};
use std::collections::BTreeSet;
fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
        Value::Number(n) => n.as_f64() != Some(0.),
    }
}
fn node_name(n: &Value, i: usize) -> String {
    let v = if truthy(&n["name"]) {
        &n["name"]
    } else {
        &n["id"]
    };
    if !truthy(v) {
        format!("index {i}")
    } else if let Some(s) = v.as_str() {
        s.to_owned()
    } else {
        crate::schemas::python_repr(v)
    }
}
fn issue(issues: &mut Vec<Value>, level: &str, category: &str, message: String, path: String) {
    issues.push(json!({"level":level,"category":category,"message":message,"path":path}));
}
fn errors(issues: &[Value], fatal: Option<&str>) -> Value {
    let mut out: Vec<String> = issues
        .iter()
        .map(|i| i["message"].as_str().unwrap_or("").to_owned())
        .collect();
    if let Some(f) = fatal
        && !out.iter().any(|s| s == f)
    {
        out.insert(0, f.into());
    }
    if out.is_empty() {
        Value::Null
    } else {
        json!(out)
    }
}
fn fatal(issues: Vec<Value>, message: &str) -> Value {
    json!({"success":false,"errors":errors(&issues,Some(message)),"issues":issues,"fatal":message})
}
pub fn sanitize_graph(data: &Value) -> Value {
    let mut out = data.clone();
    if !out.is_object() {
        return out;
    }
    if out["layers"].is_null() {
        out["layers"] = json!([]);
    }
    for (collection, nullable, lowercase) in [
        (
            "nodes",
            vec!["filePath", "lineRange", "languageNotes"],
            vec!["type", "complexity"],
        ),
        ("edges", vec!["description"], vec!["type", "direction"]),
    ] {
        if let Some(items) = out.get_mut(collection).and_then(Value::as_array_mut) {
            for item in items {
                if let Some(obj) = item.as_object_mut() {
                    for field in &nullable {
                        if obj.get(*field).is_none_or(Value::is_null) {
                            obj.remove(*field);
                        }
                    }
                    for field in &lowercase {
                        if let Some(s) = obj.get(*field).and_then(Value::as_str) {
                            obj.insert((*field).into(), json!(s.to_lowercase()));
                        }
                    }
                }
            }
        }
    }
    out
}
pub fn normalize_graph(data: &Value) -> Value {
    let mut out = data.clone();
    if !out.is_object() {
        return out;
    }
    for (collection, table) in [
        ("nodes", "NODE_TYPE_ALIASES"),
        ("edges", "EDGE_TYPE_ALIASES"),
    ] {
        if let Some(items) = out.get_mut(collection).and_then(Value::as_array_mut) {
            for item in items {
                if let Some(t) = item["type"].as_str()
                    && let Some(alias) = tables()["schema"][table][t].as_str()
                {
                    item["type"] = json!(alias);
                }
            }
        }
    }
    out
}
pub fn auto_fix_graph(data: &Value) -> (Value, Vec<Value>) {
    let mut out = data.clone();
    let mut issues = vec![];
    if let Some(nodes) = out.get_mut("nodes").and_then(Value::as_array_mut) {
        for (i, n) in nodes.iter_mut().enumerate() {
            if !n.is_object() {
                continue;
            }
            let name = node_name(n, i);
            for (field, default) in [
                ("type", "file"),
                ("complexity", "moderate"),
                ("summary", ""),
            ] {
                if field == "summary" && !n["tags"].is_array() {
                    n["tags"] = json!([]);
                    issue(
                        &mut issues,
                        "auto-corrected",
                        "missing-field",
                        format!("nodes[{i}] (\"{name}\"): missing \"tags\" — defaulted to []"),
                        format!("nodes[{i}].tags"),
                    );
                }
                let missing = if field == "complexity" {
                    !truthy(&n[field])
                } else {
                    n[field].as_str().is_none_or(str::is_empty)
                };
                if missing {
                    n[field] = if field == "summary" && truthy(&n["name"]) {
                        n["name"].clone()
                    } else {
                        json!(if field == "summary" {
                            "No summary"
                        } else {
                            default
                        })
                    };
                    let suffix = if field == "summary" {
                        "name".to_owned()
                    } else {
                        format!("\"{default}\"")
                    };
                    issue(
                        &mut issues,
                        "auto-corrected",
                        "missing-field",
                        format!(
                            "nodes[{i}] (\"{name}\"): missing \"{field}\" — defaulted to {suffix}"
                        ),
                        format!("nodes[{i}].{field}"),
                    );
                } else if field == "complexity"
                    && let Some(c) = n[field].as_str()
                    && let Some(alias) = tables()["schema"]["COMPLEXITY_ALIASES"][c].as_str()
                {
                    let original = c.to_owned();
                    n[field] = json!(alias);
                    issue(
                        &mut issues,
                        "auto-corrected",
                        "alias",
                        format!(
                            "nodes[{i}] (\"{name}\"): complexity \"{original}\" — mapped to \"{alias}\""
                        ),
                        format!("nodes[{i}].complexity"),
                    );
                }
            }
        }
    }
    if let Some(edges) = out.get_mut("edges").and_then(Value::as_array_mut) {
        for (i, e) in edges.iter_mut().enumerate() {
            if !e.is_object() {
                continue;
            }
            for (field, default) in [("type", "depends_on"), ("direction", "forward")] {
                if e[field].as_str().is_none_or(str::is_empty) {
                    e[field] = json!(default);
                    issue(
                        &mut issues,
                        "auto-corrected",
                        "missing-field",
                        format!("edges[{i}]: missing \"{field}\" — defaulted to \"{default}\""),
                        format!("edges[{i}].{field}"),
                    );
                }
            }
            if let Some(d) = e["direction"].as_str()
                && let Some(alias) = tables()["schema"]["DIRECTION_ALIASES"][d].as_str()
            {
                let original = d.to_owned();
                e["direction"] = json!(alias);
                issue(
                    &mut issues,
                    "auto-corrected",
                    "alias",
                    format!("edges[{i}]: direction \"{original}\" — mapped to \"{alias}\""),
                    format!("edges[{i}].direction"),
                );
            }
            if e["weight"].is_null() {
                e["weight"] = json!(0.5);
                issue(
                    &mut issues,
                    "auto-corrected",
                    "missing-field",
                    format!("edges[{i}]: missing \"weight\" — defaulted to 0.5"),
                    format!("edges[{i}].weight"),
                );
            } else if let Some(w) = e["weight"].as_str() {
                let original = w.to_owned();
                let parsed = w.trim().parse::<f64>().ok().filter(|f| !f.is_nan());
                e["weight"] = json!(parsed.unwrap_or(0.5));
                let message = if parsed.is_some() {
                    format!("edges[{i}]: weight was string \"{original}\" — coerced to number")
                } else {
                    format!(
                        "edges[{i}]: weight \"{original}\" is not a valid number — defaulted to 0.5"
                    )
                };
                issue(
                    &mut issues,
                    "auto-corrected",
                    "type-coercion",
                    message,
                    format!("edges[{i}].weight"),
                );
            }
            if let Some(w) = e["weight"].as_f64()
                && !(0.0..=1.0).contains(&w)
            {
                let original = e["weight"].to_string();
                e["weight"] = json!(w.clamp(0., 1.));
                issue(
                    &mut issues,
                    "auto-corrected",
                    "out-of-range",
                    format!(
                        "edges[{i}]: weight {original} clamped to {:?}",
                        w.clamp(0., 1.)
                    ),
                    format!("edges[{i}].weight"),
                );
            }
        }
    }
    (out, issues)
}
fn message(error: &crate::Error) -> String {
    match error {
        crate::Error::Validation { message, .. } => message.clone(),
        _ => error.to_string(),
    }
}
pub fn validate_graph(data: &Value) -> Value {
    if !data.is_object() {
        return fatal(vec![], "Invalid input: not an object");
    }
    let (fixed, mut issues) = auto_fix_graph(&normalize_graph(&sanitize_graph(data)));
    for name in ["nodes", "edges", "layers"] {
        if !fixed[name].is_null() && !fixed[name].is_array() {
            let text = format!("\"{name}\" must be an array when present");
            issue(
                &mut issues,
                "fatal",
                "invalid-collection",
                text.clone(),
                name.into(),
            );
            return fatal(issues, &text);
        }
    }
    let Ok(project) = crate::models::validate_model("_ProjectMetaModel", &fixed["project"]) else {
        return fatal(issues, "Missing or invalid project metadata");
    };
    let mut nodes = vec![];
    for (i, n) in array(&fixed, "nodes").iter().enumerate() {
        match crate::models::validate_model("_GraphNodeModel", n) {
            Ok(n) => nodes.push(crate::models::exclude_model_none("_GraphNodeModel", &n)),
            Err(e) => {
                let name = node_name(n, i);
                issue(
                    &mut issues,
                    "dropped",
                    "invalid-node",
                    format!("nodes[{i}] (\"{name}\"): {} — removed", message(&e)),
                    format!("nodes[{i}]"),
                );
            }
        }
    }
    if nodes.is_empty() {
        return fatal(issues, "No valid nodes found in knowledge graph");
    }
    let ids: BTreeSet<_> = nodes.iter().filter_map(|n| n["id"].as_str()).collect();
    let mut edges = vec![];
    for (i, e) in array(&fixed, "edges").iter().enumerate() {
        let e = match crate::models::validate_model("_GraphEdgeModel", e) {
            Ok(e) => crate::models::exclude_model_none("_GraphEdgeModel", &e),
            Err(e) => {
                issue(
                    &mut issues,
                    "dropped",
                    "invalid-edge",
                    format!("edges[{i}]: {} — removed", message(&e)),
                    format!("edges[{i}]"),
                );
                continue;
            }
        };
        if let Some(field) = ["source", "target"]
            .into_iter()
            .find(|f| !ids.contains(e[*f].as_str().unwrap_or("")))
        {
            issue(
                &mut issues,
                "dropped",
                "invalid-reference",
                format!(
                    "edges[{i}]: {field} \"{}\" does not exist in nodes — removed",
                    e[field].as_str().unwrap_or("")
                ),
                format!("edges[{i}].{field}"),
            );
        } else {
            edges.push(e);
        }
    }
    let mut layers = vec![];
    for (i, l) in array(&fixed, "layers").iter().enumerate() {
        match crate::models::validate_model("_LayerModel", l) {
            Ok(mut l) => {
                l["nodeIds"] = json!(
                    crate::strings(&l["nodeIds"])
                        .into_iter()
                        .filter(|s| ids.contains(s.as_str()))
                        .collect::<Vec<_>>()
                );
                layers.push(l);
            }
            Err(e) => issue(
                &mut issues,
                "dropped",
                "invalid-layer",
                format!("layers[{i}]: {} — removed", message(&e)),
                format!("layers[{i}]"),
            ),
        }
    }
    json!({"success":true,"data":{"version":fixed["version"].as_str().unwrap_or("1.0.0"),"project":project,"nodes":nodes,"edges":edges,"layers":layers},"errors":errors(&issues,None),"issues":issues})
}
