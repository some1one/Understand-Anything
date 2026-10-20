//! Incremental update phases. Git is injectable; persistence follows the existing
//! phase boundaries, including metadata-only stops and fingerprint guards.
use crate::{Error, Result, array, batch_merge, fingerprints, strings};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    process::Command,
};
const FILE_TYPES: &[&str] = &[
    "file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint",
];
fn ua(root: &Path, name: &str) -> PathBuf {
    root.join(".understand-anything").join(name)
}
fn inter(root: &Path, name: &str) -> PathBuf {
    ua(root, "intermediate").join(name)
}
fn read(path: &Path) -> Value {
    crate::persistence::read_json(path).unwrap_or(Value::Null)
}
fn write(path: &Path, v: &Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    crate::persistence::write_json(path, v)
}
fn required(path: &Path) -> Result<Value> {
    let v = read(path);
    if v.is_object() {
        Ok(v)
    } else {
        Err(Error::Invalid(format!(
            "{} missing or unreadable",
            path.file_name().unwrap_or_default().to_string_lossy()
        )))
    }
}
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
pub fn node_file_path(n: &Value) -> Option<String> {
    n["filePath"]
        .as_str()
        .filter(|s| !s.is_empty())
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
}
pub fn graph_file_paths(g: &Value) -> BTreeSet<String> {
    array(g, "nodes")
        .iter()
        .filter_map(node_file_path)
        .filter(|p| !p.is_empty())
        .collect()
}
pub fn is_source_file(path: &str) -> bool {
    let base = path.rsplit('/').next().unwrap_or(path);
    let Some((_, ext)) = base.rsplit_once('.') else {
        return false;
    };
    [
        "ts", "tsx", "js", "jsx", "mjs", "cjs", "py", "go", "rs", "java", "rb", "cpp", "cc", "c",
        "h", "hpp", "cs", "swift", "kt", "php",
    ]
    .contains(&ext.to_lowercase().as_str())
}
pub trait GitClient {
    fn head(&self, root: &Path) -> Option<String>;
    fn changed_files(&self, root: &Path, previous: &str, current: &str) -> Option<Vec<String>>;
}
pub struct ProcessGit;
impl GitClient for ProcessGit {
    fn head(&self, root: &Path) -> Option<String> {
        let out = Command::new("git")
            .args(["rev-parse", "HEAD"])
            .current_dir(root)
            .output()
            .ok()?;
        let head = String::from_utf8_lossy(&out.stdout).trim().to_owned();
        if out.status.success() && !head.is_empty() {
            Some(head)
        } else {
            None
        }
    }
    fn changed_files(&self, root: &Path, prev: &str, head: &str) -> Option<Vec<String>> {
        crate::context_helpers::changed_paths(root, &format!("{prev}..{head}")).ok()
    }
}
pub fn write_meta(root: &Path, commit: &str, analyzed: Option<usize>) -> Result<()> {
    let path = ua(root, "meta.json");
    let mut meta = read(&path);
    if !meta.is_object() {
        meta = json!({});
    }
    meta["lastAnalyzedAt"] = json!(crate::now_iso());
    meta["gitCommitHash"] = json!(commit);
    if meta.get("version").is_none() {
        meta["version"] = json!("1.0.0");
    }
    if let Some(n) = analyzed {
        meta["analyzedFiles"] = json!(n);
    }
    write(&path, &meta)
}
pub fn preflight(root: &Path, force: bool) -> Result<Value> {
    preflight_with_git(root, force, &ProcessGit)
}
pub fn preflight_with_git(root: &Path, force: bool, git: &dyn GitClient) -> Result<Value> {
    let mut state = json!({"status":"STOP","action":"NO_GRAPH","reason":"No existing knowledge graph found. Run `/understand` first to create one.","projectRoot":root,"previousCommit":null,"currentCommit":null,"changedSourceFiles":[],"metadataUpdated":false});
    if !ua(root, "knowledge-graph.json").exists() {
        return Ok(state);
    }
    let meta = read(&ua(root, "meta.json"));
    state["action"] = json!("NO_META");
    state["reason"] = json!("No analysis metadata found. Run `/understand` to create a baseline.");
    let previous = s(&meta, "gitCommitHash");
    if previous.is_empty() {
        return Ok(state);
    }
    state["previousCommit"] = json!(previous);
    let Some(current) = git.head(root) else {
        state["reason"] = json!("Not a git repository or cannot read HEAD; auto-update aborted.");
        return Ok(state);
    };
    state["currentCommit"] = json!(current);
    if current == previous && !force {
        state["action"] = json!("UP_TO_DATE");
        state["reason"] = json!("Knowledge graph is already up to date.");
        return Ok(state);
    }
    let Some(changed) = git.changed_files(root, previous, &current) else {
        state["reason"] = json!(format!(
            "Cannot diff {previous}..{current}; stored baseline commit may be unknown. Run `/understand` to re-baseline."
        ));
        return Ok(state);
    };
    let source: Vec<_> = changed
        .iter()
        .filter(|p| is_source_file(p))
        .cloned()
        .collect();
    let (action, reason, kept) = if changed.is_empty() {
        (
            "NO_CHANGES",
            "No files changed between commits. Metadata updated.",
            vec![],
        )
    } else if changed
        .iter()
        .any(|p| crate::context_helpers::is_ignore_file(p))
    {
        let graph = required(&ua(root, "knowledge-graph.json"))?;
        let scan = crate::scan::scan_project(root)?;
        let paths: BTreeSet<_> = graph_file_paths(&graph)
            .into_iter()
            .chain(array(&scan, "files").iter().filter_map(|f| {
                f["path"]
                    .as_str()
                    .filter(|p| is_source_file(p))
                    .map(str::to_owned)
            }))
            .collect();
        ("PROCEED", "", paths.into_iter().collect())
    } else if source.is_empty() {
        (
            "NO_SOURCE_CHANGES",
            "Only non-source files changed. Metadata updated.",
            vec![],
        )
    } else {
        let filter = crate::scan::create_ignore_filter(root)?;
        let mut kept: Vec<_> = source
            .into_iter()
            .filter(|p| !filter.is_ignored(p))
            .collect();
        kept.sort();
        if kept.is_empty() {
            (
                "ALL_IGNORED",
                "All changed source files are in ignored paths. Metadata updated.",
                kept,
            )
        } else {
            ("PROCEED", "", kept)
        }
    };
    state["action"] = json!(action);
    if action == "PROCEED" {
        fs::create_dir_all(inter(root, ""))?;
        state["status"] = json!("CONTINUE");
        state["reason"] = json!(format!("{} changed source file(s) to inspect.", kept.len()));
        state["changedSourceFiles"] = json!(kept);
    } else {
        write_meta(root, &current, None)?;
        state["metadataUpdated"] = json!(true);
        state["reason"] = json!(reason);
    }
    Ok(state)
}
pub fn fingerprint_check(root: &Path) -> Result<Value> {
    let state = required(&inter(root, "auto-update-state.json"))?;
    let (store, _) = fingerprints::load_fingerprint_store(&ua(root, "fingerprints.json"))?;
    let graph = read(&ua(root, "knowledge-graph.json"));
    let graph_paths = graph_file_paths(&graph);
    let filter = crate::scan::create_ignore_filter(root)?;
    let changes: Vec<_> = strings(&state["changedSourceFiles"])
        .iter()
        .map(|p| {
            if filter.is_ignored(p) && graph_paths.contains(p) {
                json!({"filePath":p,"changeLevel":"STRUCTURAL","status":"deleted","details":["file ignored"]})
            } else {
                fingerprints::classify_file_change(root, p, if graph_paths.contains(p) { store["files"].get(p) } else { None })
            }
        })
        .collect();
    let decision = fingerprints::classify_update(&changes, &graph_file_paths(&graph));
    let select = |level: &str, status: Option<&str>, exclude: bool| {
        let mut paths: Vec<_> = changes
            .iter()
            .filter(|f| {
                f["changeLevel"] == level && status.is_none_or(|s| (f["status"] == s) != exclude)
            })
            .map(|f| f["filePath"].clone())
            .collect();
        paths.sort_by(|a, b| a.as_str().cmp(&b.as_str()));
        paths
    };
    let mut analysis = json!({"action":decision["action"],"rerunArchitecture":decision["rerunArchitecture"],"reason":decision["reason"],"filesToReanalyze":select("STRUCTURAL",Some("deleted"),true),"newFiles":select("STRUCTURAL",Some("new"),false),"deletedFiles":select("STRUCTURAL",Some("deleted"),false),"cosmeticOnlyFiles":select("COSMETIC",None,false),"unchangedFiles":select("NONE",None,false),"fileChanges":changes,"metadataUpdated":false});
    if decision["action"] == "SKIP" && !s(&state, "currentCommit").is_empty() {
        write_meta(root, s(&state, "currentCommit"), None)?;
        analysis["metadataUpdated"] = json!(true);
    }
    Ok(analysis)
}
pub fn prepare_batches(root: &Path) -> Result<Value> {
    let analysis = required(&inter(root, "change-analysis.json"))?;
    let changed = strings(&analysis["filesToReanalyze"]);
    let mut scan = read(&inter(root, "scan-result.json"));
    if !scan.is_object() {
        scan = json!({"files":[],"importMap":{}});
    }
    if scan.get("files").is_none() {
        scan["files"] = json!([]);
    }
    if scan.get("importMap").is_none() {
        scan["importMap"] = json!({});
    }
    let mut known: BTreeSet<_> = array(&scan, "files")
        .iter()
        .filter_map(|f| f["path"].as_str().map(str::to_owned))
        .collect();
    for rel in &changed {
        if !known.contains(rel)
            && let Ok(bytes) = fs::read(root.join(rel))
        {
            scan["files"].as_array_mut().unwrap().push(json!({"path":rel,"language":crate::scan::detect_language(rel),"sizeLines":bytes.iter().filter(|&&b|b==b'\n').count(),"fileCategory":crate::scan::detect_category(rel)}));
            known.insert(rel.clone());
        }
    }
    let batches =
        crate::batching::compute_batches(root, &scan, Some(&changed.iter().cloned().collect()));
    write(&inter(root, "batches.json"), &batches)?;
    let graph = read(&ua(root, "knowledge-graph.json"));
    let project = &graph["project"];
    let summaries:Vec<_>=array(&batches,"batches").iter().map(|b|json!({"batchIndex":b["batchIndex"],"outputPath":inter(root,&format!("batch-{}.json",b["batchIndex"])),"files":array(b,"files").iter().map(|f|json!({"path":f["path"],"sizeLines":f["sizeLines"],"language":f["language"]})).collect::<Vec<_>>()})).collect();
    let summary = json!({"projectName":project["name"],"projectDescription":project["description"],"languages":project.get("languages").cloned().unwrap_or(json!([])),"frameworks":project.get("frameworks").cloned().unwrap_or(json!([])),"totalBatches":summaries.len(),"filesToReanalyze":changed,"allProjectFiles":known,"batches":summaries});
    write(&inter(root, "dispatch-summary.json"), &summary)?;
    Ok(summary)
}
pub fn build_arch_input(nodes: &[Value], edges: &[Value]) -> Value {
    let mut files = vec![];
    let mut ids = BTreeSet::new();
    for n in nodes {
        if let Some(path) = node_file_path(n).filter(|s| !s.is_empty())
            && FILE_TYPES.contains(&s(n, "type"))
        {
            ids.insert(s(n, "id"));
            files.push(json!({"id":n["id"],"type":n["type"],"name":n["name"].as_str().filter(|s|!s.is_empty()).unwrap_or_else(||path.rsplit('/').next().unwrap_or("")),"filePath":path,"summary":n.get("summary").cloned().unwrap_or(json!("")),"tags":n.get("tags").cloned().unwrap_or(json!([]))}));
        }
    }
    let all:Vec<_>=edges.iter().filter(|e|ids.contains(s(e,"source"))&&ids.contains(s(e,"target"))).map(|e|json!({"source":e["source"],"target":e["target"],"type":e.get("type").cloned().unwrap_or(json!("imports"))})).collect();
    let imports: Vec<_> = all
        .iter()
        .filter(|e| e["type"] == "imports")
        .cloned()
        .collect();
    json!({"fileNodes":files,"importEdges":imports,"allEdges":all})
}
pub fn apply_batches(root: &Path) -> Result<Value> {
    let _lock = crate::batch_files::lock(&inter(root, ""))?;
    let analysis = required(&inter(root, "change-analysis.json"))?;
    let graph = required(&ua(root, "knowledge-graph.json"))?;
    let targets: BTreeSet<_> = strings(&analysis["filesToReanalyze"])
        .into_iter()
        .chain(strings(&analysis["deletedFiles"]))
        .collect();
    let kept: Vec<_> = array(&graph, "nodes")
        .iter()
        .filter(|n| node_file_path(n).is_none_or(|p| !targets.contains(&p)))
        .cloned()
        .collect();
    let kept_ids: BTreeSet<_> = kept.iter().filter_map(|n| n["id"].as_str()).collect();
    let edges: Vec<_> = array(&graph, "edges")
        .iter()
        .filter(|e| {
            ["source", "target"]
                .iter()
                .all(|key| e[key].as_str().is_some_and(|id| kept_ids.contains(id)))
        })
        .collect();
    let existing = json!({"nodes":kept,"edges":edges});
    write(&inter(root, "batch-existing.json"), &existing)?;
    let re = regex::Regex::new(r"^batch-(\d+)(?:-part-(\d+))?\.json$").unwrap();
    let mut files: Vec<_> = fs::read_dir(inter(root, ""))?
        .filter_map(|e| e.ok())
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            let c = re.captures(&name)?;
            let key = vec![c[1].parse::<u64>().unwrap()];
            let mut key = key;
            if let Some(p) = c.get(2) {
                key.push(p.as_str().parse().unwrap());
            }
            Some((key, e.path()))
        })
        .collect();
    files.sort_by(|a, b| a.0.cmp(&b.0));
    let mut batches = vec![existing];
    batches.extend(files.iter().map(|(_, p)| read(p)));
    let (assembled, report) = batch_merge::merge_and_normalize(&batches);
    let merged = json!({"version":graph.get("version").cloned().unwrap_or(json!("1.0.0")),"project":graph.get("project").cloned().unwrap_or(json!({})),"nodes":assembled["nodes"],"edges":assembled["edges"],"layers":graph.get("layers").cloned().unwrap_or(json!([]))});
    write(&inter(root, "merged-graph.json"), &merged)?;
    if analysis["rerunArchitecture"] == true {
        write(
            &inter(root, "ua-arch-input.json"),
            &build_arch_input(array(&assembled, "nodes"), array(&assembled, "edges")),
        )?;
    }
    eprintln!("{}", report.join("\n"));
    Ok(merged)
}
pub fn reconcile_layers(nodes: &[Value], layers: &[Value]) -> Vec<Value> {
    let paths: BTreeMap<_, _> = nodes
        .iter()
        .filter(|n| !s(n, "id").is_empty())
        .map(|n| (s(n, "id"), node_file_path(n)))
        .collect();
    let mut seen = BTreeSet::new();
    let mut clean = vec![];
    for l in layers {
        if !l.is_object() {
            continue;
        }
        let kept: Vec<_> = strings(&l["nodeIds"])
            .into_iter()
            .filter(|id| paths.contains_key(id.as_str()) && seen.insert(id.clone()))
            .collect();
        let mut l = l.clone();
        l["nodeIds"] = json!(kept);
        clean.push(l);
    }
    let unassigned: Vec<_> = nodes
        .iter()
        .filter(|n| {
            FILE_TYPES.contains(&s(n, "type"))
                && !s(n, "id").is_empty()
                && !seen.contains(s(n, "id"))
        })
        .collect();
    let mut catch = None;
    for n in unassigned {
        let path = paths
            .get(s(n, "id"))
            .and_then(|p| p.as_deref())
            .unwrap_or("");
        let dir = crate::imports::dir_of(path);
        let mut best = None;
        let mut score = -1;
        for (i, l) in clean.iter().enumerate() {
            for id in strings(&l["nodeIds"]) {
                if let Some(Some(path)) = paths
                    .get(id.as_str())
                    .filter(|p| p.as_ref().is_some_and(|s| !s.is_empty()))
                {
                    let new_score = dir
                        .split('/')
                        .zip(crate::imports::dir_of(path).split('/'))
                        .take_while(|(a, b)| a == b)
                        .count() as i64;
                    if new_score > score {
                        score = new_score;
                        best = Some(i);
                    }
                }
            }
        }
        let idx = if score > 0 {
            best.unwrap()
        } else if let Some(i) = catch {
            i
        } else {
            let i = clean.len();
            clean.push(json!({"id":"layer:misc","name":"Miscellaneous","description":"Files not assigned to a specific architecture layer.","nodeIds":[]}));
            catch = Some(i);
            i
        };
        clean[idx]["nodeIds"]
            .as_array_mut()
            .unwrap()
            .push(n["id"].clone());
        seen.insert(s(n, "id").into());
    }
    clean
        .into_iter()
        .filter(|l| !array(l, "nodeIds").is_empty())
        .collect()
}
pub fn clean_graph(graph: &mut Value) {
    let ids: BTreeSet<_> = array(graph, "nodes")
        .iter()
        .map(|n| s(n, "id").to_owned())
        .filter(|s| !s.is_empty())
        .collect();
    let edges: Vec<_> = array(graph, "edges")
        .iter()
        .filter(|e| e.is_object() && ids.contains(s(e, "source")) && ids.contains(s(e, "target")))
        .cloned()
        .collect();
    graph["edges"] = json!(edges);
}
pub fn finalize(root: &Path) -> Result<Value> {
    let analysis = read(&inter(root, "change-analysis.json"));
    let mut merged = required(&inter(root, "merged-graph.json"))?;
    let state = read(&inter(root, "auto-update-state.json"));
    let current = if s(&state, "currentCommit").is_empty() {
        s(&analysis, "currentCommit")
    } else {
        s(&state, "currentCommit")
    };
    let fresh = if analysis["rerunArchitecture"] == true {
        read(&inter(root, "layers.json"))
    } else {
        Value::Null
    };
    let layers = fresh
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_else(|| array(&merged, "layers"));
    merged["layers"] = json!(reconcile_layers(array(&merged, "nodes"), layers));
    clean_graph(&mut merged);
    write(&ua(root, "knowledge-graph.json"), &merged)?;
    crate::query_dictionary::refresh(&ua(root, "knowledge-graph.json"))?;
    let changed: Vec<_> = strings(&analysis["filesToReanalyze"])
        .into_iter()
        .chain(strings(&analysis["deletedFiles"]))
        .collect();
    let (before, after) = match fingerprints::patch_and_save_fingerprints(
        &ua(root, "fingerprints.json"),
        root,
        &changed,
        if current.is_empty() {
            None
        } else {
            Some(current)
        },
    ) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("finalize: fingerprint patch aborted: {e}");
            return Err(e);
        }
    };
    let updated = !current.is_empty();
    if updated {
        write_meta(root, current, Some(graph_file_paths(&merged).len()))?;
    }
    let summary = json!({"status":"UPDATED","action":analysis.get("action").cloned().unwrap_or(json!("PARTIAL_UPDATE")),"reason":analysis.get("reason").cloned().unwrap_or(json!("")),"filesChecked":array(&analysis,"fileChanges").len(),"structuralChanges":array(&analysis,"fileChanges").iter().filter(|f|f["changeLevel"]=="STRUCTURAL").count(),"cosmeticOnly":array(&analysis,"fileChanges").iter().filter(|f|f["changeLevel"]=="COSMETIC").count(),"newFiles":array(&analysis,"newFiles").len(),"deletedFiles":array(&analysis,"deletedFiles").len(),"nodesUpdated":array(&merged,"nodes").len(),"totalNodes":array(&merged,"nodes").len(),"totalEdges":array(&merged,"edges").len(),"metadataUpdated":updated,"outputPath":ua(root,"knowledge-graph.json")});
    eprintln!("finalize: fingerprints {before} → {after}");
    write(&inter(root, "auto-update-summary.json"), &summary)?;
    if let Ok(entries) = fs::read_dir(inter(root, "")) {
        for e in entries.flatten() {
            if e.path().is_file()
                && !["scan-result.json", "auto-update-summary.json"]
                    .contains(&e.file_name().to_string_lossy().as_ref())
            {
                let _ = fs::remove_file(e.path());
            }
        }
    }
    Ok(summary)
}
pub fn run_command(command: &str, root: &Path, force: bool) -> Result<Value> {
    match command {
        "auto_update_preflight" => {
            let v = preflight(root, force)?;
            if ua(root, "").exists() {
                write(&inter(root, "auto-update-state.json"), &v)?;
            }
            Ok(v)
        }
        "auto_update_fingerprint_check" => {
            let v = fingerprint_check(root)?;
            write(&inter(root, "change-analysis.json"), &v)?;
            Ok(v)
        }
        "auto_update_prepare_batches" => {
            let v = prepare_batches(root)?;
            eprintln!(
                "prepare-batches: {} batch(es) for {} file(s)",
                v["totalBatches"],
                array(&v, "filesToReanalyze").len()
            );
            Ok(v)
        }
        "auto_update_apply_batches" => {
            let v = apply_batches(root)?;
            Ok(
                json!({"totalNodes":array(&v,"nodes").len(),"totalEdges":array(&v,"edges").len(),"rerunArchitecture":inter(root,"ua-arch-input.json").exists()}),
            )
        }
        "auto_update_finalize" => finalize(root),
        _ => Err(Error::Invalid(format!("Unknown update phase: {command}"))),
    }
}
