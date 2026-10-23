//! Evidence-based comparison of graph symbols across source revisions.
use crate::array;
use serde_json::{Value, json};
use std::collections::BTreeSet;
fn s<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
fn kind(node: &Value) -> Option<&'static str> {
    match s(node, "type") {
        "class" => Some("class"),
        "function" | "func" | "method" => Some("callable"),
        _ => None,
    }
}
fn qualified(name: &str) -> String {
    name.replace("::", ".").replace('#', ".")
}
#[derive(Clone, PartialEq, Eq)]
struct Identity {
    kind: &'static str,
    owner: String,
    name: String,
}
struct Symbol {
    identity: Identity,
    range: Value,
}
fn valid_scope(item: &Value) -> bool {
    match s(item, "kind") {
        "file" | "unknown" => true,
        "class" => item["name"].as_str().is_some_and(|name| !name.is_empty()),
        "local" => item["id"].as_u64().is_some(),
        _ => false,
    }
}
fn valid_record(item: &Value, declaration: bool) -> bool {
    let range = &item["lineRange"];
    let range_valid = range.as_array().is_some_and(|range| range.len() == 2)
        && range[0]
            .as_u64()
            .is_some_and(|start| start > 0 && range[1].as_u64().is_some_and(|end| end >= start));
    let name_valid = if declaration {
        item["name"].as_str().is_some_and(|name| !name.is_empty())
    } else {
        item.get("name")
            .is_some_and(|name| name.is_null() || name.is_string())
    };
    range_valid && name_valid && valid_scope(&item["scope"])
}
fn valid_evidence(evidence: &Value) -> bool {
    let scopes = &evidence["declarationScopes"];
    evidence["status"] == "succeeded"
        && evidence["structure"].is_object()
        && evidence["language"]
            .as_str()
            .is_some_and(|language| !language.is_empty())
        && scopes["version"] == 1
        && ["functions", "classes"].iter().all(|key| {
            scopes[*key]
                .as_array()
                .is_some_and(|records| records.iter().all(|item| valid_record(item, true)))
        })
        && scopes["unresolved"]
            .as_array()
            .is_some_and(|records| records.iter().all(|item| valid_record(item, false)))
        && ["coverageGaps", "effects"].iter().all(|key| {
            scopes[*key].as_array().is_some_and(|records| {
                records.iter().all(|item| {
                    valid_record(item, false)
                        && item.get("kind").is_some_and(|kind| {
                            kind.is_null() || kind == "callable" || kind == "class"
                        })
                        && item["reason"].is_string()
                        && item.get("nameSuffix").is_none_or(Value::is_string)
                })
            })
        })
}

fn source_symbols(evidence: &Value) -> Vec<Symbol> {
    if !valid_evidence(evidence) {
        return vec![];
    }
    let mut result = vec![];
    for (field, kind) in [("functions", "callable"), ("classes", "class")] {
        for item in array(&evidence["declarationScopes"], field) {
            let owner = match s(&item["scope"], "kind") {
                "file" => String::new(),
                "class" => s(&item["scope"], "name").to_owned(),
                _ => continue,
            };
            if let Some(name) = item["name"].as_str().filter(|name| !name.is_empty()) {
                result.push(Symbol {
                    identity: Identity {
                        kind,
                        owner,
                        name: name.to_owned(),
                    },
                    range: item["lineRange"].clone(),
                });
            }
        }
    }
    result
}
fn names(node: &Value, path: &str) -> BTreeSet<String> {
    let mut names = BTreeSet::from([qualified(s(node, "name"))]);
    if let Some((_, name)) = s(node, "id").split_once(&format!(":{path}:")) {
        names.insert(qualified(name));
    }
    names
}
fn resolve(node: &Value, graph: &Value, source: &[Symbol], path: &str) -> Option<Identity> {
    if s(node, "filePath") != path {
        return None;
    }
    let names = names(node, path);
    let mut candidates: Vec<_> = source
        .iter()
        .filter(|symbol| {
            Some(symbol.identity.kind) == kind(node)
                && (names.contains(&qualified(&symbol.identity.name))
                    || !symbol.identity.owner.is_empty()
                        && names.contains(&qualified(&format!(
                            "{}.{}",
                            symbol.identity.owner, symbol.identity.name
                        ))))
        })
        .collect();
    let explicit: Vec<_> = candidates
        .iter()
        .copied()
        .filter(|symbol| {
            !symbol.identity.owner.is_empty()
                && names.contains(&qualified(&format!(
                    "{}.{}",
                    symbol.identity.owner, symbol.identity.name
                )))
        })
        .collect();
    if !explicit.is_empty() {
        candidates = explicit;
    }
    let parents: BTreeSet<_> = array(graph, "edges")
        .iter()
        .filter(|edge| edge["type"] == "contains" && edge["target"] == node["id"])
        .map(|edge| s(edge, "source"))
        .collect();
    let owners: BTreeSet<_> = array(graph, "nodes")
        .iter()
        .filter(|parent| parent["type"] == "class" && parents.contains(s(parent, "id")))
        .map(|parent| qualified(s(parent, "name")))
        .collect();
    if !owners.is_empty() {
        candidates.retain(|symbol| owners.contains(&qualified(&symbol.identity.owner)));
    }
    if candidates.len() > 1 {
        if let (Some(start), Some(end)) =
            (node["lineRange"][0].as_u64(), node["lineRange"][1].as_u64())
        {
            let located: Vec<_> = candidates
                .iter()
                .copied()
                .filter(|symbol| {
                    symbol.range[0].as_u64().is_some_and(|a| start >= a)
                        && symbol.range[1].as_u64().is_some_and(|b| end <= b)
                })
                .collect();
            if located.len() == 1 {
                candidates = located;
            }
        }
    }
    (candidates.len() == 1).then(|| candidates[0].identity.clone())
}
fn compatible(effect: &Value, identity: &Identity) -> bool {
    let scope = &effect["scope"];
    if scope["kind"] == "local" {
        return false;
    }
    if !effect["kind"].is_null() && effect["kind"] != identity.kind {
        return false;
    }
    let owner = if scope["kind"] == "class" {
        s(scope, "name")
    } else {
        ""
    };
    if scope["kind"] != "unknown" && qualified(owner) != qualified(&identity.owner) {
        return false;
    }
    let name = s(effect, "name");
    if !effect["name"].is_null() && name != identity.name {
        return false;
    }
    effect
        .get("nameSuffix")
        .and_then(Value::as_str)
        .is_none_or(|suffix| identity.name.ends_with(suffix))
}
/// Compare one file's graph snapshots using independently parsed base/head evidence.
/// Unknown evidence is not permission to delete; replacements require unique
/// source and graph bindings in both revisions.
pub fn compare_file_symbols(
    path: &str,
    previous: &Value,
    current: &Value,
    base: &Value,
    head: &Value,
) -> Value {
    let old_nodes: Vec<_> = array(previous, "nodes")
        .iter()
        .filter(|node| kind(node).is_some() && s(node, "filePath") == path)
        .collect();
    let new_nodes: Vec<_> = array(current, "nodes")
        .iter()
        .filter(|node| kind(node).is_some() && s(node, "filePath") == path)
        .collect();
    let old_source = source_symbols(base);
    let new_source = source_symbols(head);
    let old_map: Vec<_> = old_nodes
        .iter()
        .map(|node| resolve(node, previous, &old_source, path))
        .collect();
    let new_map: Vec<_> = new_nodes
        .iter()
        .map(|node| resolve(node, current, &new_source, path))
        .collect();
    let mut missing = vec![];
    let mut replacements = vec![];
    for (node, identity) in old_nodes.iter().zip(&old_map) {
        let mut status = "unknown";
        let reason;
        if !valid_evidence(base) || !valid_evidence(head) {
            reason = "Strict source evidence is unavailable, failed, or incompatible";
        } else if let Some(identity) = identity {
            let same = |symbol: &&Symbol| symbol.identity == *identity;
            if old_source.iter().filter(same).count() != 1
                || old_map
                    .iter()
                    .filter(|candidate| candidate.as_ref() == Some(identity))
                    .count()
                    != 1
            {
                reason = "Old source identity or graph binding is ambiguous";
            } else {
                let source_count = new_source.iter().filter(same).count();
                let matches: Vec<_> = new_map
                    .iter()
                    .enumerate()
                    .filter(|(_, candidate)| candidate.as_ref() == Some(identity))
                    .collect();
                let ambiguous_owner = !identity.owner.is_empty()
                    && [&old_source, &new_source].iter().any(|source| {
                        source
                            .iter()
                            .filter(|symbol| {
                                symbol.identity.kind == "class"
                                    && symbol.identity.name == identity.owner
                            })
                            .count()
                            > 1
                    });
                if ambiguous_owner {
                    reason = "Declaring class is ambiguous";
                } else if source_count == 1 && matches.len() == 1 {
                    let candidate = new_nodes[matches[0].0];
                    if candidate["id"] != node["id"] {
                        replacements.push(json!({"oldId":node["id"],"newId":candidate["id"]}));
                    }
                    continue;
                } else if source_count == 1 {
                    status = "still-present";
                    reason = "Symbol remains in source but is missing or ambiguous in the graph";
                } else if source_count > 1 {
                    reason = "Current source identity is ambiguous";
                } else if new_source.is_empty() {
                    reason = "Empty structural extraction is not proof of deletion";
                } else if new_nodes
                    .iter()
                    .any(|candidate| candidate["id"] == node["id"])
                {
                    reason = "Old graph ID was reused by a different or unresolved source identity";
                } else if array(&base["declarationScopes"], "coverageGaps")
                    .iter()
                    .filter(|gap| gap["reason"] == "Unresolved declaration name")
                    .chain(array(&head["declarationScopes"], "coverageGaps"))
                    .chain(array(&head["declarationScopes"], "effects"))
                    .any(|effect| compatible(effect, identity))
                {
                    reason =
                        "Compatible declaration gaps or runtime effects prevent proving deletion";
                } else {
                    status = "deleted";
                    reason = "Scoped source identity is absent with no compatible gaps or effects";
                }
            }
        } else {
            reason = "Old graph symbol cannot be mapped uniquely to source";
        }
        missing.push(json!({"id":node["id"],"name":node["name"],"type":node["type"],"status":status,"reason":reason}));
    }
    let ok = missing.iter().all(|item| item["status"] == "deleted");
    json!({"filePath":path,"ok":ok,"beforeSymbolCount":old_nodes.len(),"afterSymbolCount":new_nodes.len(),"missing":missing,"replacements":replacements})
}

fn artifact(root: &std::path::Path, name: &str) -> std::path::PathBuf {
    crate::persistence::data_dir(root)
        .join("intermediate")
        .join(name)
}
/// Preserve the original graph across repeated preparation for the same revision.
pub fn capture_baseline(
    root: &std::path::Path,
    state: &Value,
    analysis: &Value,
    graph: &Value,
) -> crate::Result<()> {
    let path = artifact(root, "incremental-symbol-baseline.json");
    let files: BTreeSet<_> = crate::strings(&analysis["filesToReanalyze"])
        .into_iter()
        .collect();
    let baseline = json!({"version":1,"baseCommit":state["previousCommit"],"headCommit":state["currentCommit"],"files":files,"graph":graph});
    if path.exists() {
        let old = crate::persistence::read_json(&path)?;
        if old["version"] == 1
            && old["baseCommit"] == baseline["baseCommit"]
            && old["headCommit"] == baseline["headCommit"]
            && old["files"] == baseline["files"]
        {
            return Ok(());
        }
    }
    crate::persistence::write_json(&path, &baseline)
}
fn revision_source(root: &std::path::Path, revision: &str, path: &str) -> crate::Result<String> {
    if ![40, 64].contains(&revision.len()) || !revision.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(crate::Error::Invalid(
            "Symbol evidence requires a resolved source commit".into(),
        ));
    }
    if path.is_empty()
        || std::path::Path::new(path).is_absolute()
        || path.split('/').any(|part| part == "..")
    {
        return Err(crate::Error::Invalid(format!(
            "Invalid symbol source path: {path}"
        )));
    }
    let output = std::process::Command::new("git")
        .args([
            "show",
            "--no-ext-diff",
            "--no-textconv",
            &format!("{revision}:./{path}"),
        ])
        .current_dir(root)
        .output()?;
    if !output.status.success() {
        return Err(crate::Error::Invalid(format!(
            "Cannot read {path} from source revision {revision}"
        )));
    }
    String::from_utf8(output.stdout)
        .map_err(|_| crate::Error::Invalid(format!("Source is not UTF-8: {path}")))
}
/// Validate immediately before publication. Reports are diagnostic only: each
/// attempt rechecks source evidence rather than trusting a previous green report.
pub fn validate_prepared(
    root: &std::path::Path,
    state: &Value,
    analysis: &Value,
    current: &mut Value,
) -> crate::Result<Value> {
    if !current["nodes"].is_array() || !current["edges"].is_array() {
        return Err(crate::Error::Invalid(
            "Invalid assembled graph for symbol validation".into(),
        ));
    }
    let mut ids = BTreeSet::new();
    if array(current, "nodes")
        .iter()
        .any(|node| s(node, "id").is_empty() || !ids.insert(s(node, "id")))
    {
        return Err(crate::Error::Invalid(
            "Assembled graph contains missing or duplicate node IDs".into(),
        ));
    }
    let path = artifact(root, "incremental-symbol-baseline.json");
    let selected: BTreeSet<_> = crate::strings(&analysis["filesToReanalyze"])
        .into_iter()
        .collect();
    let fallback = crate::persistence::read_json(
        &crate::persistence::data_dir(root).join("knowledge-graph.json"),
    )?;
    let has_symbols = |graph: &Value| {
        array(graph, "nodes")
            .iter()
            .any(|node| kind(node).is_some() && selected.contains(s(node, "filePath")))
    };
    if !path.exists() && !has_symbols(&fallback) {
        return Ok(json!({"version":1,"ok":true,"files":[],"unresolvedFiles":[]}));
    }
    let baseline = crate::persistence::read_json(&path).map_err(|_| {
        crate::Error::Invalid(
            "Missing or unreadable incremental symbol baseline; prepare the update again".into(),
        )
    })?;
    let expected: BTreeSet<_> = crate::strings(&baseline["files"]).into_iter().collect();
    if baseline["version"] != 1
        || baseline["baseCommit"] != state["previousCommit"]
        || baseline["headCommit"] != state["currentCommit"]
        || expected != selected
        || !baseline["graph"]["nodes"].is_array()
        || !baseline["graph"]["edges"].is_array()
    {
        return Err(crate::Error::Invalid(
            "Symbol baseline does not match the prepared update".into(),
        ));
    }
    let previous = &baseline["graph"];
    let mut reports = vec![];
    let mut unresolved = vec![];
    let mut errors = vec![];
    for path in &selected {
        if !array(previous, "nodes")
            .iter()
            .any(|node| kind(node).is_some() && s(node, "filePath") == path)
        {
            continue;
        }
        let evidence = (|| -> crate::Result<(Value, Value)> {
            let before = revision_source(root, s(&baseline, "baseCommit"), path)?;
            let after = revision_source(root, s(&baseline, "headCommit"), path)?;
            Ok((
                crate::structure::analyze_file_strict(path, &before),
                crate::structure::analyze_file_strict(path, &after),
            ))
        })();
        let (base, head) = match evidence {
            Ok(pair) => pair,
            Err(error) => {
                errors.push(format!("{path}: {error}"));
                (Value::Null, Value::Null)
            }
        };
        let report = compare_file_symbols(path, previous, current, &base, &head);
        if report["ok"] != true {
            unresolved.push(path.clone());
        }
        reports.push(report);
    }
    let retry_path = artifact(root, "incremental-symbol-retry.json");
    let retry = if retry_path.exists() {
        crate::persistence::read_json(&retry_path)?
    } else {
        Value::Null
    };
    let active_retry = retry.is_object()
        && retry["baseCommit"] == baseline["baseCommit"]
        && retry["headCommit"] == baseline["headCommit"];
    if active_retry {
        let paths: BTreeSet<_> = crate::strings(&retry["files"]).into_iter().collect();
        if retry["status"] != "ready"
            || !paths.is_subset(&selected)
            || !retry["graph"]["nodes"].is_array()
            || !retry["graph"]["edges"].is_array()
        {
            return Err(crate::Error::Invalid(
                "Invalid or interrupted symbol retry state".into(),
            ));
        }
        // A repair must not lose new symbols discovered by the first attempt.
        for path in &paths {
            let evidence = revision_source(root, s(&baseline, "headCommit"), path)
                .map(|source| crate::structure::analyze_file_strict(path, &source));
            let head = match evidence {
                Ok(value) => value,
                Err(error) => {
                    errors.push(error.to_string());
                    Value::Null
                }
            };
            let mut result = compare_file_symbols(path, &retry["graph"], current, &head, &head);
            result["phase"] = json!("repair");
            if result["ok"] != true && !unresolved.contains(path) {
                unresolved.push(path.clone());
            }
            reports.push(result);
        }
    }
    // An old ID cannot silently acquire another file's symbol identity.
    for old in array(previous, "nodes")
        .iter()
        .filter(|node| kind(node).is_some() && selected.contains(s(node, "filePath")))
    {
        for new in array(current, "nodes")
            .iter()
            .filter(|node| node["id"] == old["id"])
        {
            if new["filePath"] != old["filePath"] || kind(new) != kind(old) {
                errors.push(format!(
                    "Symbol ID changed file ownership or kind: {}",
                    s(old, "id")
                ));
            }
        }
    }
    let mut replacement_targets = std::collections::BTreeMap::new();
    for replacement in reports.iter().flat_map(|file| array(file, "replacements")) {
        let old = s(replacement, "oldId");
        let new = s(replacement, "newId");
        if replacement_targets
            .insert(old, new)
            .is_some_and(|previous| previous != new)
        {
            errors.push(format!("Conflicting symbol replacements for {old}"));
        }
    }
    let ok = unresolved.is_empty() && errors.is_empty();
    let report = json!({"version":1,"ok":ok,"baseCommit":baseline["baseCommit"],"headCommit":baseline["headCommit"],"graphHash":crate::fingerprints::content_hash(&serde_json::to_string(current)?),"files":reports,"unresolvedFiles":unresolved,"errors":errors});
    crate::persistence::write_json(&artifact(root, "incremental-symbol-report.json"), &report)?;
    if !ok {
        return Err(crate::Error::Invalid("Unresolved incremental symbol loss; inspect incremental-symbol-report.json. Graph and baseline were not published".into()));
    }
    // Restore previous incoming relationships using only validated ID replacements.
    let remaps: std::collections::BTreeMap<_, _> = array(&report, "files")
        .iter()
        .flat_map(|file| array(file, "replacements"))
        .map(|item| (s(item, "oldId"), s(item, "newId")))
        .collect();
    let remap = |source: &Value| {
        let mut graph = source.clone();
        for node in graph["nodes"].as_array_mut().unwrap() {
            if let Some(id) = remaps.get(s(node, "id")) {
                node["id"] = json!(id);
            }
        }
        for edge in graph["edges"].as_array_mut().unwrap() {
            for key in ["source", "target"] {
                if let Some(id) = remaps.get(s(edge, key)) {
                    edge[key] = json!(id);
                }
            }
        }
        graph
    };
    if active_retry {
        let paths = crate::strings(&retry["files"]).into_iter().collect();
        crate::updates::restore_inbound_edges(&remap(&retry["graph"]), current, &paths)?;
    }
    crate::updates::restore_inbound_edges(&remap(previous), current, &selected)?;
    Ok(report)
}
