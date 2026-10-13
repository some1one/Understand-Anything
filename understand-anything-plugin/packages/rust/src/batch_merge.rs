//! Deterministic fragment normalization and relationship recovery.
use crate::{Result, array, strings};
use serde_json::{Map, Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};
const PREFIXES: &[&str] = &[
    "file", "func", "function", "class", "module", "concept", "config", "document", "service",
    "table", "endpoint", "pipeline", "schema", "resource", "domain", "flow", "step", "article",
    "entity", "topic", "claim", "source",
];
const JS: &[&str] = &[".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue"];
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn num(v: &Value) -> f64 {
    v.as_f64()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
        .or_else(|| v.as_bool().map(|b| if b { 1. } else { 0. }))
        .unwrap_or(0.)
}
fn repr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(b) => if *b { "True" } else { "False" }.into(),
        _ => v.to_string(),
    }
}
pub fn normalize_direction(v: &Value) -> String {
    let low = v.as_str().unwrap_or("").to_lowercase();
    match low.as_str() {
        "both" | "mutual" => "bidirectional".into(),
        "forward" | "backward" | "bidirectional" => low,
        _ => "forward".into(),
    }
}
pub fn normalize_node_id(id: &str, node: &Value) -> String {
    let mut id = id.to_owned();
    for p in PREFIXES {
        if id.starts_with(&format!("{p}:{p}:")) {
            id = id[p.len() + 1..].into();
            break;
        }
    }
    let parts: Vec<_> = id.split(':').collect();
    if parts.len() >= 3
        && !PREFIXES.contains(&parts[0])
        && PREFIXES.contains(&parts[1])
        && !parts[2..].join(":").is_empty()
    {
        id = parts[1..].join(":");
    }
    if let Some(rest) = id.strip_prefix("func:") {
        id = format!("function:{rest}");
    }
    if !PREFIXES.iter().any(|p| id.starts_with(&format!("{p}:"))) {
        let t = node["type"].as_str().unwrap_or("file");
        let prefix = if t == "func" {
            "function"
        } else if PREFIXES.contains(&t) {
            t
        } else {
            "file"
        };
        if ["function", "class"].contains(&t) {
            let path = s(node, "filePath");
            let name = node["name"].as_str().unwrap_or(&id);
            id = format!(
                "{prefix}:{}:{name}",
                if path.is_empty() {
                    "__nofilepath__"
                } else {
                    path
                }
            );
        } else {
            id = format!("{prefix}:{id}");
        }
    }
    id
}
pub fn classify_id_fix(original: &str, corrected: &str) -> String {
    for p in PREFIXES {
        if original.starts_with(&format!("{p}:{p}:")) {
            return format!("{p}:{p}: → {p}: (double prefix)");
        }
    }
    let parts: Vec<_> = original.split(':').collect();
    if parts.len() >= 3 && !PREFIXES.contains(&parts[0]) && PREFIXES.contains(&parts[1]) {
        return format!(
            "<project>:{}: → {}: (project-name prefix)",
            parts[1], parts[1]
        );
    }
    if original.starts_with("func:") && corrected.starts_with("function:") {
        return "func: → function: (prefix canonicalization)".into();
    }
    if !PREFIXES
        .iter()
        .any(|p| original.starts_with(&format!("{p}:")))
    {
        return format!(
            "bare path → {}: (missing prefix)",
            corrected.split(':').next().unwrap_or("")
        );
    }
    format!("{original} → {corrected}")
}
pub fn normalize_complexity(v: &Value) -> (&'static str, &'static str) {
    if let Some(s) = v.as_str() {
        match s.trim().to_lowercase().as_str() {
            "simple" => ("simple", "valid"),
            "moderate" => ("moderate", "valid"),
            "complex" => ("complex", "valid"),
            "low" | "easy" => ("simple", "mapped"),
            "medium" | "intermediate" => ("moderate", "mapped"),
            "high" | "hard" | "difficult" => ("complex", "mapped"),
            _ => ("moderate", "unknown"),
        }
    } else if v.is_number() || v.is_boolean() {
        let n = num(v).trunc();
        (
            if n <= 3. {
                "simple"
            } else if n <= 6. {
                "moderate"
            } else {
                "complex"
            },
            "mapped",
        )
    } else {
        ("moderate", "unknown")
    }
}
fn splitname(path: &str) -> (&str, &str) {
    let base = path.rsplit('/').next().unwrap_or(path);
    match base.rfind('.') {
        Some(i) if i > 0 => (&base[..i], &base[i..]),
        _ => (base, ""),
    }
}
pub fn is_test_path(path: &str) -> bool {
    let (stem, ext) = splitname(path);
    if JS.contains(&ext) {
        return stem.ends_with(".test") || stem.ends_with(".spec");
    }
    match ext {
        ".go" => stem.ends_with("_test"),
        ".py" | ".c" | ".cpp" | ".cc" => stem.starts_with("test_") || stem.ends_with("_test"),
        ".java" => ["Test", "Tests", "IT"].iter().any(|s| stem.ends_with(s)),
        ".kt" | ".cs" => stem.ends_with("Test") || stem.ends_with("Tests"),
        _ => false,
    }
}
fn join(dir: &str, name: &str) -> String {
    if dir.is_empty() {
        name.into()
    } else {
        format!("{dir}/{name}")
    }
}
fn add(out: &mut Vec<String>, path: String) {
    if !path.is_empty() && !out.contains(&path) {
        out.push(path);
    }
}
fn js_candidates(out: &mut Vec<String>, dir: &str, stem: &str, ext: &str) {
    add(out, join(dir, &format!("{stem}{ext}")));
    for e in JS {
        add(out, join(dir, &format!("{stem}{e}")));
    }
}
pub fn production_candidates(path: &str) -> Vec<String> {
    let (stem, ext) = splitname(path);
    let seg: Vec<_> = path.split('/').filter(|s| !s.is_empty()).collect();
    let dirs = &seg[..seg.len().saturating_sub(1)];
    let dir = dirs.join("/");
    let mut out = vec![];
    if JS.contains(&ext) {
        if let Some(base) = stem
            .strip_suffix(".test")
            .or_else(|| stem.strip_suffix(".spec"))
        {
            js_candidates(&mut out, &dir, base, ext);
            if dirs
                .last()
                .is_some_and(|s| ["__tests__", "test", "spec", "tests"].contains(s))
            {
                js_candidates(&mut out, &dirs[..dirs.len() - 1].join("/"), base, ext);
            }
            if dirs
                .first()
                .is_some_and(|s| ["tests", "test", "__tests__"].contains(s))
            {
                for root in ["src", "app", "lib", ""] {
                    js_candidates(
                        &mut out,
                        join(root, &dirs[1..].join("/")).trim_end_matches('/'),
                        base,
                        ext,
                    );
                }
            }
        }
    } else if ext == ".go" {
        if let Some(base) = stem.strip_suffix("_test") {
            add(&mut out, join(&dir, &format!("{base}.go")));
        }
    } else if ext == ".py" {
        if let Some(base) = stem
            .strip_prefix("test_")
            .or_else(|| stem.strip_suffix("_test"))
        {
            add(&mut out, join(&dir, &format!("{base}.py")));
            if dirs.last().is_some_and(|s| ["tests", "test"].contains(s)) {
                add(
                    &mut out,
                    join(&dirs[..dirs.len() - 1].join("/"), &format!("{base}.py")),
                );
            }
            if dirs.first().is_some_and(|s| ["tests", "test"].contains(s)) {
                for root in ["src", "app", "lib", ""] {
                    add(
                        &mut out,
                        join(
                            join(root, &dirs[1..].join("/")).trim_end_matches('/'),
                            &format!("{base}.py"),
                        ),
                    );
                }
            }
        }
    } else if [".java", ".kt", ".cs"].contains(&ext) {
        let suffixes = if ext == ".java" {
            vec!["Tests", "Test", "IT"]
        } else {
            vec!["Tests", "Test"]
        };
        if let Some(base) = suffixes.iter().find_map(|s| stem.strip_suffix(s)) {
            if ext != ".cs" {
                let lang = if ext == ".java" { "java" } else { "kotlin" };
                if dirs.len() >= 3 && dirs[..3] == ["src", "test", lang] {
                    let mut prod = vec!["src", "main", lang];
                    prod.extend_from_slice(&dirs[3..]);
                    add(&mut out, join(&prod.join("/"), &format!("{base}{ext}")));
                }
                add(&mut out, join(&dir, &format!("{base}{ext}")));
            } else {
                add(&mut out, join(&dir, &format!("{base}.cs")));
                if let Some(i) = dirs
                    .iter()
                    .rposition(|s| ["tests", "test"].contains(&s.to_lowercase().as_str()))
                {
                    add(&mut out, join(&dirs[..i].join("/"), &format!("{base}.cs")));
                    let mut prod = dirs[..i].to_vec();
                    prod.push("src");
                    prod.extend_from_slice(&dirs[i + 1..]);
                    add(&mut out, join(&prod.join("/"), &format!("{base}.cs")));
                }
                if let Some(top) = dirs.first()
                    && let Some(sibling) = top
                        .strip_suffix(".Tests")
                        .or_else(|| top.strip_suffix(".Test"))
                        .filter(|s| !s.is_empty())
                {
                    let mut prod = vec![sibling];
                    prod.extend_from_slice(&dirs[1..]);
                    add(&mut out, join(&prod.join("/"), &format!("{base}.cs")));
                }
            }
        }
    } else if [".c", ".cpp", ".cc"].contains(&ext)
        && let Some(base) = stem
            .strip_prefix("test_")
            .or_else(|| stem.strip_suffix("_test"))
    {
        add(&mut out, join(&dir, &format!("{base}{ext}")));
    }
    out
}
fn file_path(n: &Value) -> Option<String> {
    let id = s(n, "id");
    id.strip_prefix("file:").map(|tail| {
        n["filePath"]
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or(tail)
            .into()
    })
}
fn swap(edge: &mut Value) {
    let src = edge["source"].clone();
    edge["source"] = edge["target"].clone();
    edge["target"] = src;
    edge["direction"] = json!("forward");
    edge["description"] = json!(if s(edge, "description").is_empty() {
        "Direction corrected (was test → production)".into()
    } else {
        format!("{} [direction corrected]", s(edge, "description"))
    });
}
pub fn link_tests(
    nodes: &mut Map<String, Value>,
    edges: &mut Vec<Value>,
) -> (usize, usize, usize, usize) {
    let mut bypath = BTreeMap::new();
    let mut types = BTreeMap::new();
    let mut tests = vec![];
    for n in nodes.values() {
        if let Some(path) = file_path(n) {
            bypath.insert(path.clone(), s(n, "id").to_owned());
            let test = is_test_path(&path);
            types.insert(s(n, "id").to_owned(), test);
            if test {
                tests.push((path, s(n, "id").to_owned()));
            }
        }
    }
    let mut covered = BTreeMap::<(String, String), usize>::new();
    let mut swapped = BTreeSet::new();
    let mut out: Vec<Value> = vec![];
    let mut dropped = 0;
    for mut e in std::mem::take(edges) {
        if e["type"] != "tested_by" {
            out.push(e);
            continue;
        }
        let (src, tgt) = (s(&e, "source").to_owned(), s(&e, "target").to_owned());
        let pair = match (types.get(&src), types.get(&tgt)) {
            (Some(false), Some(true)) => (src, tgt, false),
            (Some(true), Some(false)) => (tgt, src, true),
            _ => {
                dropped += 1;
                continue;
            }
        };
        let key = (pair.0, pair.1);
        if let Some(&i) = covered.get(&key) {
            if num(&e["weight"]) > num(&out[i]["weight"]) {
                if pair.2 {
                    swap(&mut e);
                    swapped.insert(key);
                } else {
                    swapped.remove(&key);
                }
                out[i] = e;
            }
            dropped += 1;
        } else {
            if pair.2 {
                swap(&mut e);
                swapped.insert(key.clone());
            }
            covered.insert(key, out.len());
            out.push(e);
        }
    }
    let paired: BTreeSet<_> = covered.keys().map(|(_, t)| t.clone()).collect();
    let mut added = 0;
    for (path, id) in tests {
        if paired.contains(&id) {
            continue;
        }
        for candidate in production_candidates(&path) {
            if let Some(prod) = bypath.get(&candidate)
                && !is_test_path(&candidate)
                && !covered.contains_key(&(prod.clone(), id.clone()))
            {
                covered.insert((prod.clone(), id.clone()), out.len());
                out.push(json!({"source":prod,"target":id,"type":"tested_by","direction":"forward","weight":0.5,"description":"Path-based pairing (deterministic)"}));
                added += 1;
                break;
            }
        }
    }
    let mut tagged = 0;
    for (prod, _) in covered.keys() {
        if let Some(n) = nodes.get_mut(prod) {
            if !n["tags"].is_array() {
                n["tags"] = json!([]);
            }
            let tags = n["tags"].as_array_mut().unwrap();
            if !tags.contains(&json!("tested")) {
                tags.push(json!("tested"));
                tagged += 1;
            }
        }
    }
    *edges = out;
    (added, dropped, tagged, swapped.len())
}
fn bump(counts: &mut Map<String, Value>, key: String) {
    let n = counts.get(&key).and_then(Value::as_u64).unwrap_or(0);
    counts.insert(key, json!(n + 1));
}
fn ranked(counts: &Map<String, Value>) -> Vec<(&String, u64)> {
    let mut v: Vec<_> = counts
        .iter()
        .map(|(k, v)| (k, v.as_u64().unwrap()))
        .collect();
    v.sort_by_key(|(_, v)| std::cmp::Reverse(*v));
    v
}
fn total(counts: &Map<String, Value>) -> u64 {
    counts.values().filter_map(Value::as_u64).sum()
}
pub fn merge_and_normalize(batches: &[Value]) -> (Value, Vec<String>) {
    let all: Vec<_> = batches
        .iter()
        .flat_map(|b| array(b, "nodes"))
        .cloned()
        .collect();
    let mut edges: Vec<_> = batches
        .iter()
        .flat_map(|b| array(b, "edges"))
        .cloned()
        .collect();
    let input_nodes = all.len();
    let input_edges = edges.len();
    let mut id_patterns = Map::new();
    let mut complexity_patterns = Map::new();
    let mut unknown_complexity = Map::new();
    let mut unknown_types = Map::new();
    let mut unfixable = vec![];
    let mut mapping = BTreeMap::new();
    let mut normalized = vec![];
    for (i, mut n) in all.into_iter().enumerate() {
        let original = s(&n, "id").to_owned();
        if original.is_empty() {
            unfixable.push(format!(
                "Node[{i}] has no 'id' field (name={}, type={})",
                n["name"].as_str().unwrap_or("?"),
                n["type"].as_str().unwrap_or("?")
            ));
            continue;
        }
        let t = s(&n, "type");
        if !t.is_empty() && !PREFIXES.contains(&t) {
            bump(&mut unknown_types, t.into());
        }
        let corrected = normalize_node_id(&original, &n);
        if original != corrected {
            bump(&mut id_patterns, classify_id_fix(&original, &corrected));
            mapping.insert(original, corrected.clone());
            n["id"] = json!(corrected);
        }
        normalized.push(n);
    }
    for n in &mut normalized {
        let (norm, status) = normalize_complexity(&n["complexity"]);
        if status == "mapped" {
            bump(
                &mut complexity_patterns,
                format!("{} → \"{norm}\"", repr(&n["complexity"])),
            );
        } else if status == "unknown" {
            bump(
                &mut unknown_complexity,
                format!(
                    "complexity {} → defaulted to \"moderate\"",
                    repr(&n["complexity"])
                ),
            );
        }
        n["complexity"] = json!(norm);
    }
    let mut rewritten = 0;
    for e in &mut edges {
        let src = s(e, "source").to_owned();
        let tgt = s(e, "target").to_owned();
        let ns = mapping.get(&src).unwrap_or(&src);
        let nt = mapping.get(&tgt).unwrap_or(&tgt);
        if *ns != src || *nt != tgt {
            rewritten += 1;
            e["source"] = json!(ns);
            e["target"] = json!(nt);
        }
    }
    let mut nodes = Map::new();
    let mut duplicates = 0;
    for n in normalized {
        if nodes.insert(s(&n, "id").into(), n).is_some() {
            duplicates += 1;
        }
    }
    let (added, dropped, tagged, swapped) = link_tests(&mut nodes, &mut edges);
    let mut indices = BTreeMap::<(String, String, String, String), usize>::new();
    let mut clean: Vec<Value> = vec![];
    for mut e in edges {
        let src = s(&e, "source").to_owned();
        let tgt = s(&e, "target").to_owned();
        let ty = s(&e, "type").to_owned();
        let direction = normalize_direction(&e["direction"]);
        e["direction"] = json!(direction);
        if !nodes.contains_key(&src) || !nodes.contains_key(&tgt) {
            let mut missing = vec![];
            if !nodes.contains_key(&src) {
                missing.push(format!("source '{src}'"));
            }
            if !nodes.contains_key(&tgt) {
                missing.push(format!("target '{tgt}'"));
            }
            unfixable.push(format!(
                "Edge {src} → {tgt} ({ty}): dropped, missing {}",
                missing.join(", ")
            ));
            continue;
        }
        let key = (src, tgt, ty, direction);
        if let Some(&i) = indices.get(&key) {
            if num(&e["weight"]) > num(&clean[i]["weight"]) {
                clean[i] = e;
            }
        } else {
            indices.insert(key, clean.len());
            clean.push(e);
        }
    }
    let mut report = vec![format!("Input: {input_nodes} nodes, {input_edges} edges")];
    let mut fixed = vec![];
    for (p, n) in ranked(&id_patterns) {
        fixed.push(format!("  {n:>4} × {p}"));
    }
    for (p, n) in ranked(&complexity_patterns) {
        fixed.push(format!("  {n:>4} × complexity {p}"));
    }
    for (n, msg) in [
        (
            rewritten,
            "edge references rewritten after ID normalization",
        ),
        (duplicates, "duplicate node IDs removed (kept last)"),
        (
            swapped,
            "tested_by edges flipped (test → production became production → test)",
        ),
        (
            dropped,
            "tested_by edges dropped (orphan endpoint or test↔test / prod↔prod pair)",
        ),
    ] {
        if n > 0 {
            fixed.push(format!("  {n:>4} × {msg}"));
        }
    }
    if !fixed.is_empty() {
        report.push(String::new());
        report.push(format!(
            "Fixed ({} corrections):",
            total(&id_patterns)
                + total(&complexity_patterns)
                + (rewritten + duplicates + swapped + dropped) as u64
        ));
        report.extend(fixed);
    }
    if added > 0 || tagged > 0 {
        report.extend([String::new(),"Tested-by linker:".into(),format!("  {added:>4} × tested_by edges produced (path-convention supplement, production → test)"),format!("  {tagged:>4} × production nodes tagged \"tested\"")]);
    }
    let unfixable_total =
        unfixable.len() as u64 + total(&unknown_complexity) + total(&unknown_types);
    if unfixable_total > 0 {
        report.extend([
            String::new(),
            format!("Could not fix ({unfixable_total} issues — needs agent review):"),
        ]);
        for (t, n) in ranked(&unknown_types) {
            report.push(format!(
                "  {n:>4} × unknown node type \"{t}\" (not in schema, kept as-is)"
            ));
        }
        for (p, n) in ranked(&unknown_complexity) {
            report.push(format!("  {n:>4} × {p}"));
        }
        report.extend(unfixable.into_iter().map(|s| format!("  - {s}")));
    }
    report.extend([
        String::new(),
        format!("Output: {} nodes, {} edges", nodes.len(), clean.len()),
    ]);
    (
        json!({"nodes":nodes.into_iter().map(|(_,v)|v).collect::<Vec<_>>(),"edges":clean}),
        report,
    )
}
pub fn recover_imports_from_scan(assembled: &mut Value, path: &Path) -> (usize, Vec<String>) {
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    if !path.is_file() {
        return (
            0,
            vec![format!("  importMap recovery skipped — {name} not found")],
        );
    }
    let scan = match crate::persistence::read_json(path) {
        Ok(v) => v,
        Err(e) => {
            return (
                0,
                vec![format!(
                    "  importMap recovery skipped — could not parse {name}: {e}"
                )],
            );
        }
    };
    let Some(map) = scan["importMap"].as_object() else {
        return (
            0,
            vec![format!(
                "  importMap recovery skipped — no importMap field in {name}"
            )],
        );
    };
    let known: BTreeSet<String> = array(&scan, "files")
        .iter()
        .filter_map(|f| f["path"].as_str().map(str::to_owned))
        .collect();
    let ids: BTreeSet<_> = array(assembled, "nodes")
        .iter()
        .filter(|n| n["type"] == "file")
        .map(|n| s(n, "id").to_owned())
        .collect();
    let sources: BTreeSet<_> = array(assembled, "nodes")
        .iter()
        .filter(|n| n["type"] == "file" && n["stub"] != true)
        .map(|n| s(n, "id").to_owned())
        .collect();
    let mut existing: BTreeSet<_> = array(assembled, "edges")
        .iter()
        .filter(|e| e["type"] == "imports")
        .map(|e| (s(e, "source").to_owned(), s(e, "target").to_owned()))
        .collect();
    let (mut recovered, mut no_src, mut no_tgt) = (0, 0, 0);
    for (src, targets) in map {
        if !targets.is_array() {
            continue;
        }
        let src = format!("file:{src}");
        if !sources.contains(&src) {
            if !targets.as_array().unwrap().is_empty() {
                no_src += 1;
            }
            continue;
        }
        for target in strings(targets).into_iter().filter(|s| !s.is_empty()) {
            let tgt = format!("file:{target}");
            if !ids.contains(&tgt) && !known.contains(&target) {
                no_tgt += 1;
                continue;
            }
            if src != tgt && existing.insert((src.clone(), tgt.clone())) {
                assembled["edges"].as_array_mut().unwrap().push(json!({"source":src,"target":tgt,"type":"imports","direction":"forward","weight":0.7,"recoveredFromImportMap":true}));
                recovered += 1;
            }
        }
    }
    let mut report = vec![format!(
        "  Recovered {recovered} `imports` edges from importMap ({} entries scanned)",
        map.len()
    )];
    if no_src > 0 {
        report.push(format!(
            "  Skipped {no_src} importMap source files with no `file:` node in graph"
        ));
    }
    if no_tgt > 0 {
        report.push(format!(
            "  Skipped {no_tgt} importMap target paths with no `file:` node in graph"
        ));
    }
    *assembled = crate::merge::add_boundary_stubs(assembled, &known);
    (recovered, report)
}
pub fn load_batch(path: &Path) -> Option<Value> {
    match crate::persistence::read_json(path) {
        Err(e) => {
            eprintln!(
                "  Warning: skipping {}: {e}",
                path.file_name().unwrap_or_default().to_string_lossy()
            );
            None
        }
        Ok(v) => {
            for k in ["nodes", "edges"] {
                if !v[k].is_array() {
                    eprintln!(
                        "  Warning: skipping {}: missing or invalid '{k}' array",
                        path.file_name().unwrap_or_default().to_string_lossy()
                    );
                    return None;
                }
            }
            Some(v)
        }
    }
}
pub fn merge_batch_directory(root: &Path) -> Result<Value> {
    let dir = root.join(".understand-anything/intermediate");
    if !dir.is_dir() {
        return Err(crate::Error::Invalid(format!(
            "Error: {} does not exist",
            dir.display()
        )));
    }
    let numeric = regex::Regex::new(r"batch-(\d+)").unwrap();
    let exact = regex::Regex::new(r"^batch-(\d+)(?:-part-(\d+))?\.json").unwrap();
    let mut files: Vec<_> = std::fs::read_dir(&dir)?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            p.file_name().is_some_and(|s| {
                s.to_string_lossy().starts_with("batch-") && s.to_string_lossy().ends_with(".json")
            })
        })
        .collect();
    files.sort();
    files.sort_by_key(|p| {
        numeric
            .captures(&p.file_name().unwrap().to_string_lossy())
            .and_then(|c| c[1].parse::<u64>().ok())
            .unwrap_or(0)
    });
    let empty_plan = crate::persistence::read_json(&dir.join("batches.json")).is_ok_and(|plan| {
        plan["batches"].as_array().is_some_and(Vec::is_empty) && plan["totalBatches"] == 0
    });
    if files.is_empty() && empty_plan {
        let graph = json!({"nodes":[], "edges":[]});
        crate::persistence::write_json(&dir.join("assembled-graph.json"), &graph)?;
        return Ok(graph);
    }
    if files.is_empty() {
        return Err(crate::Error::Invalid(
            "Error: no batch-*.json files found in intermediate/".into(),
        ));
    }
    let mut groups = BTreeMap::<u64, Vec<Option<u64>>>::new();
    let mut unrecognized = vec![];
    for p in &files {
        let name = p.file_name().unwrap().to_string_lossy();
        if let Some(c) = exact.captures(&name) {
            groups
                .entry(c[1].parse().unwrap())
                .or_default()
                .push(c.get(2).and_then(|m| m.as_str().parse().ok()));
        } else {
            unrecognized.push(name.to_string());
        }
    }
    let preview = unrecognized
        .iter()
        .take(5)
        .cloned()
        .collect::<Vec<_>>()
        .join(", ");
    let suffix = if unrecognized.len() > 5 {
        format!(" (+{} more)", unrecognized.len() - 5)
    } else {
        String::new()
    };
    if !unrecognized.is_empty() {
        eprintln!(
            "Warning: merge-batch-graphs: {} batch file(s) with unrecognized filenames will be DROPPED — files: {preview}{suffix} — fix the file-analyzer agent to use only batch-<N>.json or batch-<N>-part-<K>.json patterns",
            unrecognized.len()
        );
    }
    eprintln!(
        "Found {} batch files ({} logical batches, {} multi-part):",
        files.len(),
        groups.len(),
        groups.values().filter(|v| v.len() > 1).count()
    );
    let mut missing_warnings = vec![];
    for (index, parts) in groups {
        let present: BTreeSet<_> = parts.into_iter().flatten().collect();
        if let Some(&max) = present.last() {
            let missing: Vec<_> = (1..=max).filter(|p| !present.contains(p)).collect();
            if !missing.is_empty() {
                let msg = format!(
                    "batch {index} has parts {:?} but missing part {missing:?} — possible truncated write — affected nodes/edges may be lost",
                    present.into_iter().collect::<Vec<_>>()
                );
                eprintln!("Warning: merge: {msg}");
                missing_warnings.push(msg);
            }
        }
    }
    let mut batches = vec![];
    for p in files {
        let name = p.file_name().unwrap().to_string_lossy();
        if unrecognized.iter().any(|s| s == &name) {
            continue;
        }
        if let Some(b) = load_batch(&p) {
            eprintln!(
                "  {name}: {} nodes, {} edges",
                array(&b, "nodes").len(),
                array(&b, "edges").len()
            );
            batches.push(b);
        }
    }
    if batches.is_empty() {
        return Err(crate::Error::Invalid(
            "Error: no valid batch files loaded".into(),
        ));
    }
    // Add scan-backed boundary nodes before normalization drops dangling edges.
    let mut combined = json!({
        "nodes": batches.iter().flat_map(|b| array(b, "nodes")).collect::<Vec<_>>(),
        "edges": batches.iter().flat_map(|b| array(b, "edges")).collect::<Vec<_>>()
    });
    if let Ok(scan) = crate::persistence::read_json(&dir.join("scan-result.json")) {
        let known = array(&scan, "files")
            .iter()
            .filter_map(|f| f["path"].as_str().map(str::to_owned))
            .collect();
        combined = crate::merge::add_boundary_stubs(&combined, &known);
    }
    let (mut graph, mut report) = merge_and_normalize(&[combined]);
    let (_, recovery) = recover_imports_from_scan(&mut graph, &dir.join("scan-result.json"));
    if !missing_warnings.is_empty() {
        report.extend([
            String::new(),
            format!(
                "Warning: {} batch(es) with missing parts — some nodes/edges silently dropped:",
                missing_warnings.len()
            ),
        ]);
        report.extend(missing_warnings.into_iter().map(|s| format!("  - {s}")));
    }
    if !unrecognized.is_empty() {
        report.extend([String::new(),format!("Warning: dropped {} batch file(s) with unrecognized filenames — files: {preview}{suffix} — fix the file-analyzer agent to use only batch-<N>.json or batch-<N>-part-<K>.json patterns (every node/edge in these files was excluded from the final graph)",unrecognized.len())]);
    }
    if !recovery.is_empty() {
        report.extend([String::new(), "Imports edge recovery:".into()]);
        report.extend(recovery);
    }
    eprintln!();
    for line in report {
        eprintln!("{line}");
    }
    let output = dir.join("assembled-graph.json");
    let text = serde_json::to_string_pretty(&graph)?;
    std::fs::write(&output, &text)?;
    eprintln!(
        "\nWritten to {} ({:.0} KB)",
        output.display(),
        (text.len() as f64 / 1024.).round_ties_even()
    );
    Ok(graph)
}
