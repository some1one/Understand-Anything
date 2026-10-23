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
    crate::persistence::data_dir(&root).join(name)
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
    fn worktree_changes(&self, _root: &Path) -> Option<Vec<String>> { Some(vec![]) }
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
    fn worktree_changes(&self, root: &Path) -> Option<Vec<String>> {
        let mut paths = BTreeSet::new();
        for args in [
            vec!["diff", "--cached", "--no-ext-diff", "--no-renames", "--name-only", "-z", "--relative", "--", "."],
            vec!["diff", "--no-ext-diff", "--no-renames", "--name-only", "-z", "--relative", "--", "."],
            vec!["ls-files", "--others", "--exclude-standard", "-z", "--", "."],
        ] {
            let out = Command::new("git").args(args).current_dir(root).output().ok()?;
            if !out.status.success() { return None; }
            let text = String::from_utf8(out.stdout).ok()?;
            paths.extend(text.split('\0').filter(|path| !path.is_empty()).map(str::to_owned));
        }
        Some(paths.into_iter().collect())
    }
}
pub fn relevant_worktree_changes(root: &Path, git: &dyn GitClient) -> Result<Vec<String>> {
    let paths = git.worktree_changes(root).ok_or_else(|| Error::Invalid("Cannot inspect Git working tree".into()))?;
    let filter = scope_filter(root)?;
    Ok(paths.into_iter().filter(|path| {
        let name = path.rsplit('/').next().unwrap_or(path);
        if name == ".understandignore" { return true; }
        if path.starts_with(".ua/") || path.starts_with(".understand-anything/") { return false; }
        if name == ".gitignore" { return true; }
        ![".ps1", ".psm1", ".psd1", ".bat", ".cmd"].contains(&crate::scan::extension(path).as_str())
            && !filter.is_ignored(path)
    }).collect())
}
fn verify_prepared_revision(root: &Path) -> Result<()> {
    let state = read(&inter(root, "auto-update-state.json"));
    let expected = s(&state, "currentCommit");
    if expected.is_empty() { return Ok(()); }
    if ProcessGit.head(root).as_deref() != Some(expected) {
        return Err(Error::Invalid("HEAD changed since incremental preflight; prepare the update again".into()));
    }
    let dirty = relevant_worktree_changes(root, &ProcessGit)?;
    if !dirty.is_empty() {
        return Err(Error::Invalid(format!("Relevant uncommitted changes prevent incremental analysis: {}", dirty.join(", "))));
    }
    Ok(())
}

fn published_excludes(root: &Path) -> Result<Vec<String>> {
    let path = ua(root, "meta.json");
    if !path.exists() { return Ok(vec![]); }
    let meta = required(&path)?;
    match meta.get("excludePatterns") {
        None => Ok(vec![]),
        Some(value) if value.as_array().is_some_and(|v| v.iter().all(Value::is_string)) => Ok(strings(value)),
        _ => Err(Error::Invalid("Published excludePatterns must be an array of strings".into())),
    }
}
fn scope_filter(root: &Path) -> Result<crate::scan::IgnoreFilter> {
    crate::scan::create_ignore_filter_with_patterns(root, &published_excludes(root)?)
}
fn scoped_scan(root: &Path) -> Result<Value> {
    crate::scan::scan_project_with_patterns(root, &published_excludes(root)?)
}
/// Advance snapshot identity while preserving descriptive and extension fields.
fn refresh_project_metadata(graph: &mut Value, scan: &Value, commit: &str) -> Result<()> {
    if !graph["nodes"].is_array() || !graph["edges"].is_array() {
        return Err(Error::Invalid("Cannot refresh metadata of an invalid saved graph".into()));
    }
    if !graph["project"].is_object() { graph["project"] = json!({}); }
    if scan["files"].is_array() {
        let languages: BTreeSet<_> = array(scan,"files").iter()
            .filter_map(|file| file["language"].as_str()).filter(|language| !language.is_empty()).collect();
        graph["project"]["languages"] = json!(languages);
    }
    graph["project"]["analyzedAt"] = json!(crate::now_iso());
    if !commit.is_empty() { graph["project"]["gitCommitHash"] = json!(commit); }
    Ok(())
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
    let dirty = relevant_worktree_changes(root, git)?;
    if !dirty.is_empty() {
        state["action"] = json!("DIRTY_WORKTREE");
        state["reason"] = json!("Commit or stash relevant uncommitted changes before incremental analysis.");
        state["dirtyPaths"] = json!(dirty);
        return Ok(state);
    }
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
    let had_changes = !changed.is_empty();
    let changed: Vec<_> = changed
        .into_iter()
        .filter(|path| {
            // Ignore generated snapshots in either directory, but retain user ignore
            // rules: changing those must still refresh/prune the analyzed inventory.
            crate::context_helpers::is_ignore_file(path)
                || !(path.starts_with(".ua/") || path.starts_with(".understand-anything/"))
        })
        .collect();
    if had_changes && changed.is_empty() {
        state["action"] = json!("GENERATED_ONLY");
        state["reason"] = json!(
            "Only generated graph artifacts changed. The baseline remains associated with the analyzed source commit."
        );
        return Ok(state);
    }
    let source: Vec<_> = changed
        .iter()
        // Every category scanned by this fork can affect the graph, not only
        // programming-language source files. Keep deleted paths in this set too.
        .filter(|p| {
            ![".ps1", ".psm1", ".psd1", ".bat", ".cmd"]
                .contains(&crate::scan::extension(p).as_str())
        })
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
        let scan = scoped_scan(root)?;
        if !array(&scan, "failures").is_empty() {
            state["action"] = json!("SCAN_FAILED");
            state["reason"] = json!("Cannot reconcile ignore changes with an incomplete project inventory. Resolve scan failures and retry.");
            state["scanFailures"] = scan["failures"].clone();
            return Ok(state);
        }
        let paths: BTreeSet<_> = graph_file_paths(&graph)
            .into_iter()
            .chain(
                array(&scan, "files")
                    .iter()
                    .filter_map(|f| f["path"].as_str())
                    .filter(|path| !crate::context_helpers::is_ignore_file(path))
                    .map(str::to_owned),
            )
            .collect();
        ("PROCEED", "", paths.into_iter().collect())
    } else if source.is_empty() {
        (
            "NO_SOURCE_CHANGES",
            "Only files outside the supported analysis scope changed. Metadata updated.",
            vec![],
        )
    } else {
        let filter = scope_filter(root)?;
        let mut kept: Vec<_> = source
            .into_iter()
            .filter(|p| !filter.is_ignored(p))
            .collect();
        kept.sort();
        if kept.is_empty() {
            (
                "ALL_IGNORED",
                "All changed project files are in ignored paths. Metadata updated.",
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
        state["reason"] = json!(format!(
            "{} changed project file(s) to inspect.",
            kept.len()
        ));
        state["changedSourceFiles"] = json!(kept);
    } else {
        write_meta(root, &current, None)?;
        state["metadataUpdated"] = json!(true);
        state["reason"] = json!(reason);
    }
    Ok(state)
}
pub fn fingerprint_check(root: &Path) -> Result<Value> {
    verify_prepared_revision(root)?;
    let state = required(&inter(root, "auto-update-state.json"))?;
    let (store, _) = fingerprints::load_fingerprint_store(&ua(root, "fingerprints.json"))?;
    let graph = read(&ua(root, "knowledge-graph.json"));
    let graph_paths = graph_file_paths(&graph);
    let filter = scope_filter(root)?;
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
        verify_prepared_revision(root)?;
        let mut graph = required(&ua(root, "knowledge-graph.json"))?;
        refresh_project_metadata(&mut graph, &read(&inter(root,"scan-result.json")), s(&state,"currentCommit"))?;
        write(&ua(root,"knowledge-graph.json"), &graph)?;
        write_meta(root, s(&state, "currentCommit"), None)?;
        analysis["metadataUpdated"] = json!(true);
    }
    Ok(analysis)
}
pub fn prepare_batches(root: &Path) -> Result<Value> {
    verify_prepared_revision(root)?;
    let analysis = required(&inter(root, "change-analysis.json"))?;
    let changed = strings(&analysis["filesToReanalyze"]);
    let baseline = read(&inter(root, "scan-result.json"));
    let current = scoped_scan(root)?;
    if !array(&current, "failures").is_empty() {
        return Err(Error::Invalid(format!(
            "Project scan reported failures; incremental preparation aborted: {}",
            current["failures"]
        )));
    }
    let known: BTreeSet<String> = array(&current, "files").iter()
        .filter_map(|f| f["path"].as_str().map(str::to_owned)).collect();
    for path in &changed {
        if !known.contains(path) {
            return Err(Error::Invalid(format!(
                "Incremental analysis target is absent from the current inventory: {path}"
            )));
        }
    }
    let previous: BTreeSet<String> = array(&baseline, "files").iter()
        .filter_map(|f| f["path"].as_str().map(str::to_owned)).collect();
    let resolver_changed = ["filesToReanalyze", "deletedFiles", "cosmeticOnlyFiles"]
        .iter().flat_map(|key| strings(&analysis[*key]))
        .any(|path| matches!(path.rsplit('/').next(), Some("tsconfig.json" | "composer.json" | "go.mod" | "Package.swift")));
    let cache_complete = baseline["importMap"].as_object().is_some_and(|map| {
        map.len() == known.len() && known.iter().all(|path| {
            map.get(path).and_then(Value::as_array).is_some_and(|targets| {
                targets.iter().all(|target| target.as_str().is_some_and(|p| known.contains(p)))
            })
        })
    });
    // Added/deleted paths can change resolution in unchanged importers. Resolver
    // configuration edits likewise require refreshing the whole inventory.
    let refresh_all = known != previous || resolver_changed || !cache_complete;
    let mut request = json!({"projectRoot":root,"files":current["files"]});
    if !refresh_all {
        request["analysisPaths"] = json!(changed);
    }
    let refreshed = crate::imports::extract_import_map(&request)?;
    let mut imports = if refresh_all { json!({}) } else { baseline["importMap"].clone() };
    for (path, targets) in refreshed["importMap"].as_object().unwrap() {
        imports[path] = targets.clone();
    }
    let mut scan = if baseline.is_object() { baseline } else { json!({}) };
    for (key, value) in current.as_object().unwrap() {
        scan[key] = value.clone();
    }
    scan.as_object_mut().unwrap().remove("failures");
    if current.get("excludePatterns").is_none() { scan.as_object_mut().unwrap().remove("excludePatterns"); }
    scan["importMap"] = imports;
    scan["importMapRefreshPaths"] = json!(refreshed["importMap"].as_object().unwrap().keys().collect::<Vec<_>>());
    let batches =
        crate::batching::compute_batches(root, &scan, Some(&changed.iter().cloned().collect()));
    let graph = read(&ua(root, "knowledge-graph.json"));
    let state = read(&inter(root, "auto-update-state.json"));
    if graph["nodes"].is_array() {
        crate::incremental_symbols::capture_baseline(root, &state, &analysis, &graph)?;
    }
    // Do not publish any preparation output until both scanning and import
    // extraction have succeeded.
    write(&inter(root, "scan-result.json"), &scan)?;
    write(&inter(root, "batches.json"), &batches)?;
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
/// Replace only imports whose whole-file source was refreshed by preparation.
/// Other relationships and unrefreshed sources retain their existing payloads.
pub fn refresh_graph_imports(graph: &Value, import_map: &Value, paths: &[String]) -> Result<Value> {
    let (index, _) = batch_merge::whole_file_node_index(array(graph, "nodes"));
    for path in paths {
        if !import_map[path].as_array().is_some_and(|targets| targets.iter().all(Value::is_string)) {
            return Err(Error::Invalid(format!("Missing or invalid refreshed imports for {path}")));
        }
    }
    let source_ids: BTreeSet<_> = paths.iter().filter_map(|path| index.get(path)).collect();
    let mut edges: Vec<_> = array(graph, "edges").iter()
        .filter(|e| !(e["type"] == "imports" && source_ids.contains(&s(e, "source").to_owned())))
        .cloned().collect();
    let mut seen: BTreeSet<_> = edges.iter()
        .map(|e| (s(e, "source").to_owned(), s(e, "target").to_owned(), s(e, "type").to_owned())).collect();
    for path in paths {
        let Some(source) = index.get(path) else { continue; };
        for target_path in strings(&import_map[path]) {
            let Some(target) = index.get(&target_path) else { continue; };
            if source != target && seen.insert((source.clone(), target.clone(), "imports".into())) {
                edges.push(json!({"source":source,"target":target,"type":"imports","direction":"forward","weight":0.7,"recoveredFromImportMap":true}));
            }
        }
    }
    let mut graph = graph.clone();
    graph["edges"] = json!(edges);
    Ok(graph)
}

pub fn validate_analyzed_file_coverage(nodes: &[Value], paths: &[String]) -> Result<()> {
    let real: Vec<_> = nodes.iter().filter(|n| n["stub"] != true).cloned().collect();
    let (index, _) = batch_merge::whole_file_node_index(&real);
    let missing: Vec<_> = paths.iter().filter(|path| {
        !index.contains_key(*path) && !real.iter().any(|node| {
            let kind = s(node, "type");
            let prefix = format!("{kind}:{path}:");
            ["table", "endpoint"].contains(&kind) && s(node, "filePath") == path.as_str()
                && s(node, "id").strip_prefix(&prefix).is_some_and(|suffix| !suffix.is_empty())
        })
    }).collect();
    if missing.is_empty() { Ok(()) } else {
        Err(Error::Invalid(format!("Assembled graph lacks analyzed-file coverage for: {}",
            missing.iter().map(|p| p.as_str()).collect::<Vec<_>>().join(", "))))
    }
}

/// Restore relationships owned by unchanged sources after replacement nodes exist.
/// Fresh analyzer edges win, and an ID reused by another file is never rebound.
pub fn restore_inbound_edges(previous: &Value, assembled: &mut Value, changed: &BTreeSet<String>) -> Result<()> {
    let old_nodes: BTreeMap<_, _> = array(previous, "nodes").iter()
        .map(|node| (s(node, "id"), node)).collect();
    let new_nodes: BTreeMap<_, _> = array(assembled, "nodes").iter()
        .map(|node| (s(node, "id"), node)).collect();
    let mut seen: BTreeSet<_> = array(assembled, "edges").iter()
        .map(|edge| (s(edge, "source").to_owned(), s(edge, "target").to_owned(), s(edge, "type").to_owned())).collect();
    let mut restored = vec![];
    for edge in array(previous, "edges") {
        let (Some(old_source), Some(old_target)) = (old_nodes.get(s(edge, "source")), old_nodes.get(s(edge, "target"))) else { continue; };
        if node_file_path(old_source).is_some_and(|path| changed.contains(&path))
            || !node_file_path(old_target).is_some_and(|path| changed.contains(&path)) {
            continue;
        }
        let (Some(new_source), Some(new_target)) = (new_nodes.get(s(edge, "source")), new_nodes.get(s(edge, "target"))) else { continue; };
        for (old, new) in [(old_source, new_source), (old_target, new_target)] {
            if node_file_path(old) != node_file_path(new) || old["type"] != new["type"] {
                return Err(Error::Invalid(format!("Preserved edge endpoint changed ownership or type: {}", s(old, "id"))));
            }
        }
        let key = (s(edge, "source").to_owned(), s(edge, "target").to_owned(), s(edge, "type").to_owned());
        if seen.insert(key) { restored.push(edge.clone()); }
    }
    assembled["edges"].as_array_mut().unwrap().extend(restored);
    Ok(())
}

pub fn prepare_symbol_retry(root: &Path) -> Result<Value> {
    verify_prepared_revision(root)?;
    let _lock = crate::batch_files::lock(&inter(root, ""))?;
    let state = required(&inter(root, "auto-update-state.json"))?;
    let analysis = required(&inter(root, "change-analysis.json"))?;
    let report = required(&inter(root, "incremental-symbol-report.json"))?;
    let graph = required(&inter(root, "merged-graph.json"))?;
    let hash = fingerprints::content_hash(&serde_json::to_string(&graph)?);
    if report["version"] != 1 || !report["errors"].is_array() || report["ok"] != false || report["baseCommit"] != state["previousCommit"] || report["headCommit"] != state["currentCommit"] || report["graphHash"] != hash {
        return Err(Error::Invalid("Symbol report does not match this failed graph and source revision".into()));
    }
    if !array(&report, "errors").is_empty() {
        return Err(Error::Invalid("Symbol validation reported source or identity errors; repair those before retrying analysis".into()));
    }
    let paths: BTreeSet<_> = strings(&report["unresolvedFiles"]).into_iter().collect();
    let original: BTreeSet<_> = strings(&analysis["filesToReanalyze"]).into_iter().collect();
    if paths.is_empty() || !paths.is_subset(&original) {
        return Err(Error::Invalid("Invalid symbol retry file inventory".into()));
    }
    let retry_path = inter(root, "incremental-symbol-retry.json");
    let old = if retry_path.exists() { required(&retry_path)? } else { Value::Null };
    if old.is_object() && old["version"] != 1 { return Err(Error::Invalid("Invalid symbol retry marker; preserve the recovery files".into())); }
    if old["baseCommit"] == state["previousCommit"] && old["headCommit"] == state["currentCommit"] {
        return Err(Error::Invalid("The single symbol repair attempt for this revision has already been used".into()));
    }
    let scan = required(&inter(root, "scan-result.json"))?;
    let known: BTreeSet<_> = array(&scan, "files").iter().filter_map(|f| f["path"].as_str().map(str::to_owned)).collect();
    if !paths.is_subset(&known) { return Err(Error::Invalid("Retry paths are missing from the prepared scan".into())); }
    let batches = crate::batching::compute_batches(root, &scan, Some(&paths));
    let summaries: Vec<_> = array(&batches,"batches").iter().map(|b| json!({"batchIndex":b["batchIndex"],"outputPath":inter(root,&format!("batch-{}.json",b["batchIndex"])),"files":b["files"]})).collect();
    let summary = json!({"projectName":graph["project"]["name"],"projectDescription":graph["project"]["description"],"languages":graph["project"]["languages"],"frameworks":graph["project"]["frameworks"],"totalBatches":summaries.len(),"filesToReanalyze":paths,"allProjectFiles":known,"batches":summaries,"symbolRepair":true,"symbolReport":report});
    let edge_candidates = crate::incremental_symbols::read_edge_candidates(root, &state, &graph)?;
    let mut retry = json!({"edgeCandidates":edge_candidates,"version":1,"baseCommit":state["previousCommit"],"headCommit":state["currentCommit"],"files":paths,"graph":graph,"status":"preparing"});
    // Consume the attempt before touching batches: a crash cannot buy a retry.
    write(&retry_path, &retry)?;
    let archive = inter(root, &format!("symbol-retry-originals-{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_nanos()));
    fs::create_dir(&archive)?;
    let pattern = regex::Regex::new(r"^batch-\d+(?:-part-\d+)?\.json$").unwrap();
    for entry in fs::read_dir(inter(root, ""))? {
        let entry = entry?;
        if pattern.is_match(&entry.file_name().to_string_lossy()) {
            fs::rename(entry.path(), archive.join(entry.file_name()))?;
        }
    }
    write(&inter(root,"batches.json"), &batches)?;
    write(&inter(root,"dispatch-summary.json"), &summary)?;
    retry["status"] = json!("ready");
    write(&retry_path, &retry)?;
    Ok(summary)
}

pub fn apply_batches(root: &Path) -> Result<Value> {
    let _lock = crate::batch_files::lock(&inter(root, ""))?;
    let analysis = required(&inter(root, "change-analysis.json"))?;
    let state = read(&inter(root, "auto-update-state.json"));
    let retry_path = inter(root, "incremental-symbol-retry.json");
    let retry = if retry_path.exists() { required(&retry_path)? } else { Value::Null };
    if retry.is_object() && retry["version"] != 1 { return Err(Error::Invalid("Invalid symbol retry marker".into())); }
    let active_retry = retry.is_object() && retry["baseCommit"] == state["previousCommit"] && retry["headCommit"] == state["currentCommit"];
    let (graph, targets): (Value, BTreeSet<String>) = if active_retry {
        if retry["status"] != "ready" || !retry["graph"]["nodes"].is_array() || !retry["graph"]["edges"].is_array() {
            return Err(Error::Invalid("Symbol retry preparation is incomplete; preserve the recovery files".into()));
        }
        (retry["graph"].clone(), strings(&retry["files"]).into_iter().collect())
    } else {
        (required(&ua(root, "knowledge-graph.json"))?, strings(&analysis["filesToReanalyze"]).into_iter().chain(strings(&analysis["deletedFiles"])).collect())
    };
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
    let re = regex::Regex::new(r"^batch-(\d+)(?:-part-(\d+))?\.json$").unwrap();
    let mut files: Vec<_> = fs::read_dir(inter(root, ""))?
        .collect::<std::io::Result<Vec<_>>>()?
        .into_iter()
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
    let mut batches = vec![existing.clone()];
    for (_, path) in &files {
        let batch = required(path)?;
        if !batch["nodes"].is_array() || !batch["edges"].is_array() {
            return Err(Error::Invalid(format!("Invalid batch fragment: {}", path.display())));
        }
        batches.push(batch);
    }
    let (mut assembled, report, candidates) = batch_merge::merge_with_edge_candidates(&batches, &(1..batches.len()).collect());
    restore_inbound_edges(&graph, &mut assembled, &targets)?;
    validate_analyzed_file_coverage(array(&assembled, "nodes"), &strings(&analysis["filesToReanalyze"]))?;
    let scan = read(&inter(root, "scan-result.json"));
    let assembled = refresh_graph_imports(&assembled, &scan["importMap"], &strings(&scan["importMapRefreshPaths"]))?;
    let merged = json!({"version":graph.get("version").cloned().unwrap_or(json!("1.0.0")),"project":graph.get("project").cloned().unwrap_or(json!({})),"nodes":assembled["nodes"],"edges":assembled["edges"],"layers":graph.get("layers").cloned().unwrap_or(json!([]))});
    write(&inter(root, "batch-existing.json"), &existing)?;
    write(&inter(root, "incremental-edge-candidates.json"), &json!({
        "version":1,"baseCommit":state["previousCommit"],"headCommit":state["currentCommit"],
        "graphHash":crate::incremental_symbols::edge_candidate_hash(&merged)?,
        "edges":candidates,"nodes":merged["nodes"]
    }))?;
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
    verify_prepared_revision(root)?;
    let analysis = read(&inter(root, "change-analysis.json"));
    let mut merged = required(&inter(root, "merged-graph.json"))?;
    validate_analyzed_file_coverage(array(&merged, "nodes"), &strings(&analysis["filesToReanalyze"]))?;
    let state = read(&inter(root, "auto-update-state.json"));
    crate::incremental_symbols::validate_prepared(root, &state, &analysis, &mut merged)?;
    // Symbol remapping restores inbound candidates; the refreshed import map
    // remains authoritative for sources whose resolver context changed.
    let scan = read(&inter(root, "scan-result.json"));
    merged = refresh_graph_imports(&merged, &scan["importMap"], &strings(&scan["importMapRefreshPaths"]))?;
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
    refresh_project_metadata(&mut merged, &scan, current)?;
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
        "auto_update_prepare_symbol_retry" => prepare_symbol_retry(root),
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
