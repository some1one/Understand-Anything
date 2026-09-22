//! Seeded Louvain communities and pipeline batch/neighbor contracts.
use crate::{Error, Result, array, parsers, strings};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

pub const MAX_COMMUNITY_SIZE: usize = 35;
pub const MIN_BATCH_SIZE: usize = 3;
pub const MAX_MERGE_TARGET: usize = 25;
pub const MAX_NEIGHBORS: usize = 50;
pub const MAX_E: usize = 20;
fn path(v: &Value) -> &str {
    v["path"].as_str().unwrap_or("")
}
fn dir(p: &str) -> &str {
    p.rsplit_once('/').map_or("", |x| x.0)
}
fn base(p: &str) -> &str {
    p.rsplit('/').next().unwrap_or(p)
}

pub fn extract_export_names(language: &str, source: &str) -> Vec<String> {
    fn collect(
        node: tree_sitter_language_pack::Node,
        source: &str,
        names: &mut Vec<String>,
        depth: usize,
    ) {
        if depth > 2 {
            return;
        }
        for i in 0..node.child_count() {
            let Some(child) = node.child(i as u32) else {
                continue;
            };
            let kind = child.kind();
            if [
                "function_declaration",
                "function_definition",
                "method_declaration",
                "class_declaration",
                "class_definition",
                "interface_declaration",
                "type_alias_declaration",
                "enum_declaration",
                "struct_item",
                "enum_item",
                "trait_item",
                "function_item",
                "type_declaration",
                "type_spec",
                "const_declaration",
                "lexical_declaration",
                "variable_declaration",
                "export_statement",
                "module",
                "variable_declarator",
                "init_declarator",
            ]
            .contains(&kind.as_str())
            {
                if let Some(name) = child.child_by_field_name("name") {
                    let text = source
                        .get(name.start_byte()..name.end_byte())
                        .unwrap_or("")
                        .to_owned();
                    if !text.is_empty() && !names.contains(&text) {
                        names.push(text);
                    }
                }
                if [
                    "export_statement",
                    "lexical_declaration",
                    "variable_declaration",
                    "const_declaration",
                ]
                .contains(&kind.as_str())
                {
                    collect(child, source, names, depth + 1);
                }
            }
        }
    }
    let mut names = vec![];
    if let Ok(tree) = parsers::parse(language, source) {
        collect(tree.root_node(), source, &mut names, 0);
    }
    names
}
pub fn extract_exports(root: &Path, files: &[Value]) -> BTreeMap<String, Vec<String>> {
    files.iter().map(|f| {
        let p = path(f);
        let names = match fs::read_to_string(root.join(p)) {
            Ok(text) => extract_export_names(f["language"].as_str().unwrap_or(""), &text),
            Err(e) => { eprintln!("Warning: compute-batches: exports extraction failed for {p} (read error: {e}) — symbols=[] in neighborMap"); vec![] }
        };
        (p.into(), names)
    }).collect()
}
pub fn count_based_assignment(files: &[Value], size: usize) -> BTreeMap<String, String> {
    let mut paths: Vec<_> = files.iter().map(path).collect();
    paths.sort();
    paths
        .iter()
        .enumerate()
        .map(|(i, p)| ((*p).into(), format!("count_{}", i / size.max(1))))
        .collect()
}

/// Multilevel modularity optimization. Stable sorted input and a private seed-42
/// shuffle make runs repeatable without depending on a library's RNG version.
pub fn run_louvain(files: &[Value], imports: &Value) -> Result<BTreeMap<String, String>> {
    if std::env::var("UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW").as_deref() == Ok("1") {
        return Err(Error::Invalid(
            "forced throw via UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW".into(),
        ));
    }
    let paths: Vec<_> = files
        .iter()
        .map(|f| path(f).to_owned())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let index: BTreeMap<_, _> = paths
        .iter()
        .enumerate()
        .map(|(i, p)| (p.as_str(), i))
        .collect();
    let mut graph = vec![BTreeMap::<usize, f64>::new(); paths.len()];
    if let Some(imports) = imports.as_object() {
        for (src, targets) in imports {
            let Some(&a) = index.get(src.as_str()) else {
                continue;
            };
            for target in strings(targets) {
                if let Some(&b) = index.get(target.as_str())
                    && a != b
                {
                    graph[a].insert(b, 1.);
                    graph[b].insert(a, 1.);
                }
            }
        }
    }
    let mut members: Vec<Vec<usize>> = (0..paths.len()).map(|i| vec![i]).collect();
    let mut seed = 42_u64;
    loop {
        let n = graph.len();
        let degree: Vec<f64> = graph.iter().map(|row| row.values().sum()).collect();
        let m2: f64 = degree.iter().sum();
        if m2 == 0. {
            break;
        }
        let mut community: Vec<_> = (0..n).collect();
        let mut totals = degree.clone();
        let mut order: Vec<_> = (0..n).collect();
        for i in (1..n).rev() {
            seed ^= seed << 13;
            seed ^= seed >> 7;
            seed ^= seed << 17;
            order.swap(i, (seed % (i as u64 + 1)) as usize);
        }
        loop {
            let mut changed = false;
            for &node in &order {
                let old = community[node];
                let mut weights = BTreeMap::<usize, f64>::new();
                for (&other, &weight) in &graph[node] {
                    if other != node {
                        *weights.entry(community[other]).or_default() += weight;
                    }
                }
                totals[old] -= degree[node];
                let old_score =
                    weights.get(&old).copied().unwrap_or(0.) - totals[old] * degree[node] / m2;
                let (mut best, mut score) = (old, old_score);
                for (&candidate, &weight) in &weights {
                    let gain = weight - totals[candidate] * degree[node] / m2;
                    if gain > score + 1e-12 {
                        best = candidate;
                        score = gain;
                    }
                }
                totals[best] += degree[node];
                community[node] = best;
                changed |= best != old;
            }
            if !changed {
                break;
            }
        }
        let labels: BTreeSet<_> = community.iter().copied().collect();
        if labels.len() == n {
            break;
        }
        let remap: BTreeMap<_, _> = labels
            .into_iter()
            .enumerate()
            .map(|(i, c)| (c, i))
            .collect();
        let mut next_graph = vec![BTreeMap::<usize, f64>::new(); remap.len()];
        let mut next_members = vec![vec![]; remap.len()];
        for i in 0..n {
            let a = remap[&community[i]];
            next_members[a].extend_from_slice(&members[i]);
            for (&j, &w) in &graph[i] {
                let b = remap[&community[j]];
                *next_graph[a].entry(b).or_default() += w;
            }
        }
        graph = next_graph;
        members = next_members;
    }
    for group in &mut members {
        group.sort();
    }
    members.sort_by(|a, b| b.len().cmp(&a.len()).then(a.first().cmp(&b.first())));
    let paths = &paths;
    Ok(members
        .iter()
        .enumerate()
        .flat_map(|(i, group)| {
            group
                .iter()
                .map(move |&j| (paths[j].clone(), format!("louvain_{i}")))
        })
        .collect())
}

pub fn build_non_code_batches(files: &[Value]) -> Vec<Value> {
    let by_path: BTreeMap<_, _> = files.iter().map(|f| (path(f), f)).collect();
    // Preserve input ordering for reserved groups A-C.
    let mut ordered = Vec::new();
    for f in files {
        if !ordered.contains(&path(f)) {
            ordered.push(path(f));
        }
    }
    let mut consumed = BTreeSet::<String>::new();
    let mut groups = vec![];
    let mut add = |paths: Vec<&str>, mergeable: bool| {
        let paths: Vec<_> = paths
            .into_iter()
            .filter(|p| !consumed.contains(*p))
            .collect();
        if !paths.is_empty() {
            groups.push(json!({"files":paths.iter().map(|p|by_path[p]).collect::<Vec<_>>(),"mergeable":mergeable}));
            consumed.extend(paths.into_iter().map(str::to_owned));
        }
    };
    let docker_dirs: BTreeSet<_> = ordered
        .iter()
        .filter(|p| base(p) == "Dockerfile")
        .map(|p| dir(p))
        .collect();
    for d in docker_dirs {
        add(
            ordered
                .iter()
                .copied()
                .filter(|p| {
                    dir(p) == d
                        && (["Dockerfile", ".dockerignore"].contains(&base(p))
                            || base(p).starts_with("docker-compose."))
                })
                .collect(),
            false,
        );
    }
    add(
        ordered
            .iter()
            .copied()
            .filter(|p| {
                p.starts_with(".github/workflows/") && (p.ends_with(".yml") || p.ends_with(".yaml"))
            })
            .collect(),
        false,
    );
    add(
        ordered
            .iter()
            .copied()
            .filter(|p| *p == ".gitlab-ci.yml" || p.starts_with(".circleci/"))
            .collect(),
        false,
    );
    let migrations: BTreeSet<_> = ordered
        .iter()
        .filter(|p| p.ends_with(".sql") && ["migration", "migrations"].contains(&base(dir(p))))
        .map(|p| dir(p))
        .collect();
    for d in migrations {
        add(
            by_path
                .keys()
                .copied()
                .filter(|p| dir(p) == d && p.ends_with(".sql"))
                .collect(),
            false,
        );
    }
    let mut remaining = BTreeMap::<&str, Vec<&Value>>::new();
    let mut directory_order = vec![];
    for (&p, &f) in &by_path {
        if !consumed.contains(p) {
            if !remaining.contains_key(dir(p)) {
                directory_order.push(dir(p));
            }
            remaining.entry(dir(p)).or_default().push(f);
        }
    }
    for directory in directory_order {
        let files = &remaining[directory];
        for chunk in files.chunks(MAX_E) {
            groups.push(json!({"files":chunk,"mergeable":true}));
        }
    }
    groups
}
pub fn merge_small_batches(batches: &[Value]) -> Vec<Value> {
    let mut keep = vec![];
    let mut pooled = vec![];
    let mut small = 0;
    for b in batches {
        if b["mergeable"] == true && array(b, "files").len() < MIN_BATCH_SIZE {
            small += 1;
            pooled.extend_from_slice(array(b, "files"));
        } else {
            keep.push(b.clone());
        }
    }
    if small > 0 {
        pooled.sort_by(|a, b| path(a).cmp(path(b)));
        let misc = pooled.len().div_ceil(MAX_MERGE_TARGET);
        eprintln!(
            "Info: compute-batches: merged {small} small batches ({} files) into {misc} misc batches — singletons and orphans consolidated",
            pooled.len()
        );
        for chunk in pooled.chunks(MAX_MERGE_TARGET) {
            keep.push(json!({"files":chunk}));
        }
    }
    keep.iter()
        .enumerate()
        .map(|(i, b)| json!({"batchIndex":i+1,"files":b["files"]}))
        .collect()
}
pub fn compute_batches(root: &Path, scan: &Value, changed: Option<&BTreeSet<String>>) -> Value {
    let files = array(scan, "files");
    let (code, noncode): (Vec<_>, Vec<_>) = files
        .iter()
        .cloned()
        .partition(|f| f["fileCategory"] == "code");
    eprintln!("Loaded {} files ({} code).", files.len(), code.len());
    let exports = extract_exports(root, &code);
    let (assignment, algorithm) = match run_louvain(&code, &scan["importMap"]) {
        Ok(a) => (a, "louvain"),
        Err(e) => {
            eprintln!(
                "Warning: compute-batches: Louvain failed ({e}) — falling back to count-based grouping (12 files/batch)"
            );
            (count_based_assignment(&code, 12), "count-fallback")
        }
    };
    let mut communities = BTreeMap::<String, Vec<String>>::new();
    for (p, c) in assignment {
        communities.entry(c).or_default().push(p);
    }
    let mut groups = vec![];
    for paths in communities.into_values() {
        if algorithm == "louvain" && paths.len() > MAX_COMMUNITY_SIZE {
            eprintln!(
                "Warning: compute-batches: community size {} > max {MAX_COMMUNITY_SIZE} — splitting via alphabetical chunking",
                paths.len()
            );
            let size = paths
                .len()
                .div_ceil(paths.len().div_ceil(MAX_COMMUNITY_SIZE));
            groups.extend(paths.chunks(size).map(|c| c.to_vec()));
        } else {
            groups.push(paths);
        }
    }
    groups.sort_by(|a, b| b.len().cmp(&a.len()).then(a.first().cmp(&b.first())));
    let meta: BTreeMap<_, _> = files.iter().map(|f| (path(f), f)).collect();
    let mut bare: Vec<_> = groups.iter().map(|g|json!({"files":g.iter().map(|p|meta[p.as_str()]).collect::<Vec<_>>(),"mergeable":true})).collect();
    bare.extend(build_non_code_batches(&noncode));
    let merged = merge_small_batches(&bare);
    let batch_of: BTreeMap<_, _> = merged
        .iter()
        .flat_map(|b| {
            array(b, "files")
                .iter()
                .map(move |f| (path(f), b["batchIndex"].clone()))
        })
        .collect();
    let mut reverse = BTreeMap::<String, Vec<String>>::new();
    if let Some(imports) = scan["importMap"].as_object() {
        for (src, targets) in imports {
            for tgt in strings(targets) {
                reverse.entry(tgt).or_default().push(src.clone());
            }
        }
    }
    let degree: BTreeMap<_, _> = code
        .iter()
        .map(|f| {
            (
                path(f),
                strings(&scan["importMap"][path(f)]).len()
                    + reverse.get(path(f)).map_or(0, Vec::len),
            )
        })
        .collect();
    let mut batches = vec![];
    for b in &merged {
        let paths: BTreeSet<_> = array(b, "files").iter().map(path).collect();
        let mut imports = json!({});
        let mut neighbors = json!({});
        for f in array(b, "files") {
            let p = path(f);
            let out = strings(&scan["importMap"][p]);
            imports[p] = json!(out);
            let all: BTreeSet<_> = out
                .iter()
                .chain(reverse.get(p).into_iter().flatten())
                .collect();
            let mut kept: Vec<_> = all.iter().filter(|p|batch_of.contains_key(p.as_str())&&!paths.contains(p.as_str())).map(|p|json!({"path":p,"batchIndex":batch_of[p.as_str()],"symbols":exports.get(p.as_str()).cloned().unwrap_or_default()})).collect();
            if all.len() > MAX_NEIGHBORS {
                kept.sort_by(|a, b| {
                    degree
                        .get(path(b))
                        .unwrap_or(&0)
                        .cmp(degree.get(path(a)).unwrap_or(&0))
                        .then(path(a).cmp(path(b)))
                });
                let before = kept.len();
                kept.truncate(MAX_NEIGHBORS);
                eprintln!(
                    "Warning: compute-batches: neighborMap for {p} has high 1-hop degree {} — exceeds soft cap of {MAX_NEIGHBORS} — keeping top {} ({} dropped)",
                    all.len(),
                    kept.len(),
                    before - kept.len()
                );
            }
            if !kept.is_empty() {
                neighbors[p] = json!(kept);
            }
        }
        if changed.is_none_or(|c| paths.iter().any(|p| c.contains(*p))) {
            batches.push(json!({"batchIndex":b["batchIndex"],"files":b["files"],"batchImportData":imports,"neighborMap":neighbors}));
        }
    }
    json!({"schemaVersion":1,"algorithm":algorithm,"totalFiles":files.len(),"totalBatches":batches.len(),"exportsByPath":exports,"batches":batches})
}
