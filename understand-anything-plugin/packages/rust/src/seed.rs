//! Deterministic graph fragments from supplied batch context and extraction output.
use crate::{array, file_graph, strings};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
fn s<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
fn complexity(lines: i64) -> &'static str {
    if lines > 200 {
        "complex"
    } else if lines >= 50 {
        "moderate"
    } else {
        "simple"
    }
}
fn title(text: &str) -> String {
    let mut start = true;
    let mut out = String::new();
    for c in text.chars() {
        if start {
            out.extend(c.to_uppercase());
        } else {
            out.extend(c.to_lowercase());
        }
        start = !c.is_alphabetic();
    }
    out
}
fn category_tags(typ: &str, category: &str, path: &str, language: &str) -> Vec<String> {
    let tags = match typ {
        "document" => vec!["documentation", "reference", "project-knowledge"],
        "config" => vec!["configuration", "build-system", "project-settings"],
        "service" | "pipeline" | "resource" => vec!["infrastructure", "automation", "deployment"],
        "schema" => vec!["schema-definition", "data-model", "validation"],
        _ => vec![
            "source-code",
            if language.is_empty() {
                "unknown-language"
            } else {
                language
            },
            "implementation",
        ],
    };
    let mut tags: Vec<String> = tags.into_iter().map(str::to_owned).collect();
    let lower = path.to_lowercase();
    if lower.ends_with(".sh") || category == "script" {
        tags.push("script".into());
    }
    for (needle, tag) in [
        ("understand_core", "architecture-analysis"),
        ("dashboard", "dashboard"),
        ("skill", "skill"),
    ] {
        if lower.contains(needle) {
            tags.push(tag.into());
        }
    }
    tags
}
fn unique_tags(first: Vec<String>, second: Vec<String>) -> Vec<String> {
    let mut tags = vec![];
    for tag in first.into_iter().chain(second) {
        if !tag.is_empty() && !tags.contains(&tag) {
            tags.push(tag);
        }
    }
    for tag in ["analysis", "project-structure", "codebase"] {
        if tags.len() >= 3 {
            break;
        }
        if !tags.iter().any(|s| s == tag) {
            tags.push(tag.into());
        }
    }
    tags.truncate(5);
    tags
}
fn file_summary(path: &str, typ: &str, language: &str, result: &Value) -> String {
    match typ {
        "document" => {
            return format!(
                "Documentation file covering project guidance or reference material for {path}."
            );
        }
        "config" => {
            return format!(
                "Configuration file that controls project tooling or package behavior for {path}."
            );
        }
        "service" | "pipeline" | "resource" => {
            return format!(
                "Infrastructure or automation file defining build, deployment, or operational behavior for {path}."
            );
        }
        "schema" => {
            return format!("Schema file defining structured data or API contracts for {path}.");
        }
        _ => {}
    }
    let mut details = vec![];
    for (key, name, suffix) in [
        ("functionCount", "function", "s"),
        ("classCount", "class", "es"),
        ("importCount", "internal import", "s"),
    ] {
        let n = result["metrics"][key].as_i64().unwrap_or(0);
        if n != 0 {
            details.push(format!("{n} {name}{}", if n == 1 { "" } else { suffix }));
        }
    }
    let lang = if language.is_empty() {
        "Source".into()
    } else {
        title(language)
    };
    if details.is_empty() {
        format!("{lang} file {path} represented as part of the project implementation graph.")
    } else {
        format!(
            "{lang} file {path} with {} identified by structural extraction.",
            details.join(", ")
        )
    }
}
fn add_edge(
    edges: &mut Vec<Value>,
    keys: &mut BTreeSet<(String, String, String)>,
    source: &str,
    target: &str,
    typ: &str,
    weight: f64,
) {
    if source != target && keys.insert((source.into(), target.into(), typ.into())) {
        edges.push(json!({"source":source,"target":target,"type":typ,"direction":"forward","weight":weight}));
    }
}
pub fn build_seed(context: &Value, extract_results: &Value) -> Value {
    let results: BTreeMap<_, _> = array(extract_results, "results")
        .iter()
        .filter_map(|r| r["path"].as_str().map(|p| (p, r)))
        .collect();
    let mut nodes = vec![];
    let mut edges = vec![];
    let mut node_ids = BTreeSet::new();
    let mut edge_keys = BTreeSet::new();
    let mut file_ids: Vec<(String, String)> = vec![];
    let empty = json!({});
    for f in array(context, "batchFiles") {
        let Some(path) = f["path"].as_str() else {
            continue;
        };
        let category = f["fileCategory"].as_str();
        let result = results.get(path).copied().unwrap_or(&empty);
        let ext = std::path::Path::new(path)
            .extension()
            .and_then(|e| e.to_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("unknown");
        let language = result["language"]
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or(ext);
        let Some((typ, id)) = file_graph::file_level_node(category, path) else {
            continue;
        };
        if !file_ids.iter().any(|(p, _)| p == path) {
            file_ids.push((path.into(), id.clone()));
        }
        if node_ids.insert(id.clone()) {
            nodes.push(json!({"id":id,"type":typ,"name":file_graph::basename(path),"filePath":path,"summary":file_summary(path,&typ,language,result),"tags":unique_tags(file_graph::deterministic_tags(category,path),category_tags(&typ,category.unwrap_or(""),path,language)),"complexity":complexity(result["nonEmptyLines"].as_i64().unwrap_or(0))}));
        }
    }
    for (path, file_id) in &file_ids {
        if !file_id.starts_with("file:") {
            continue;
        }
        let Some(result) = results.get(path.as_str()) else {
            continue;
        };
        let exported: BTreeSet<_> = array(result, "exports")
            .iter()
            .filter_map(|e| e["name"].as_str())
            .collect();
        for (key, kind) in [("functions", "function"), ("classes", "class")] {
            for symbol in array(result, key) {
                let name = s(symbol, "name");
                if name.is_empty() {
                    continue;
                }
                let range = symbol["startLine"].as_i64().zip(symbol["endLine"].as_i64());
                let span = range
                    .filter(|(a, b)| b >= a)
                    .map(|(a, b)| b - a + 1)
                    .unwrap_or(0);
                let significant = exported.contains(name)
                    || (kind == "function" && span >= 10)
                    || (kind == "class" && (span >= 20 || array(symbol, "methods").len() >= 2));
                if !significant {
                    continue;
                }
                let id = format!("{kind}:{path}:{name}");
                if node_ids.insert(id.clone()) {
                    let mut node = json!({"id":id,"type":kind,"name":name,"filePath":path,"summary":format!("{} {name} defined in {path}, included because structural extraction marked it significant for the file graph.",title(kind)),"tags":unique_tags(vec![kind.into()],category_tags("file","code",path,s(result,"language"))),"complexity":complexity(span)});
                    if let Some((a, b)) = range {
                        node["lineRange"] = json!([a, b]);
                    }
                    nodes.push(node);
                    add_edge(&mut edges, &mut edge_keys, file_id, &id, "contains", 1.);
                    if exported.contains(name) {
                        add_edge(&mut edges, &mut edge_keys, file_id, &id, "exports", 0.8);
                    }
                }
            }
        }
    }
    if let Some(imports) = context["batchImportData"].as_object() {
        for (source, targets) in imports {
            if let Some((_, id)) = file_ids
                .iter()
                .find(|(p, id)| p == source && id.starts_with("file:"))
            {
                for target in strings(targets).into_iter().filter(|s| !s.is_empty()) {
                    add_edge(
                        &mut edges,
                        &mut edge_keys,
                        id,
                        &format!("file:{target}"),
                        "imports",
                        0.7,
                    );
                }
            }
        }
    }
    json!({"batchIndex":context["batchIndex"],"nodes":nodes,"edges":edges})
}
pub fn build_batch_payloads(root: &str, batch: &Value) -> (Value, Value) {
    let files:Vec<_>=array(batch,"files").iter().filter(|f|f.is_object()).map(|f|json!({"path":f["path"],"language":f["language"],"sizeLines":f["sizeLines"],"fileCategory":f["fileCategory"]})).collect();
    let imports = batch
        .get("batchImportData")
        .filter(|v| !v.is_null())
        .cloned()
        .unwrap_or_else(|| json!({}));
    let neighbors = batch
        .get("neighborMap")
        .filter(|v| !v.is_null())
        .cloned()
        .unwrap_or_else(|| json!({}));
    (
        json!({"projectRoot":root,"batchFiles":files,"batchImportData":imports}),
        json!({"projectRoot":root,"batchIndex":batch["batchIndex"],"batchFiles":files,"batchImportData":imports,"neighborMap":neighbors}),
    )
}
