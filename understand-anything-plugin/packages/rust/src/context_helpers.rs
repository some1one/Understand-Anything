//! Native implementations behind the skill compatibility entrypoints.
use crate::{
    Error, Result, array,
    persistence::{read_json, write_json},
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
    process::Command,
};

pub fn is_ignore_file(path: &str) -> bool {
    matches!(
        path,
        ".uaignore"
            | ".understand-anything/.uaignore"
            | ".ua/.uaignore"
            | ".gitignore"
            | ".git/info/exclude"
    ) || path.ends_with("/.gitignore")
}

pub fn changed_paths(root: &Path, revision: &str) -> Result<Vec<String>> {
    let out = Command::new("git")
        .args(["diff", revision, "--name-only", "--no-renames", "-z", "--"])
        .current_dir(root)
        .output()?;
    if !out.status.success() {
        return Err(Error::Invalid(
            String::from_utf8_lossy(&out.stderr).trim().to_owned(),
        ));
    }
    let text = String::from_utf8(out.stdout).map_err(|e| Error::Invalid(e.to_string()))?;
    Ok(text
        .split('\0')
        .filter(|p| !p.is_empty())
        .map(str::to_owned)
        .collect())
}
fn git(root: &Path, args: &[&str]) -> String {
    Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_owned())
        .unwrap_or_default()
}
pub fn default_base(root: &Path) -> Option<String> {
    let branch = git(root, &["symbolic-ref", "--quiet", "--short", "HEAD"]);
    let remote = git(
        root,
        &[
            "symbolic-ref",
            "--quiet",
            "--short",
            "refs/remotes/origin/HEAD",
        ],
    );
    for candidate in [
        remote.as_str(),
        "main",
        "master",
        "origin/main",
        "origin/master",
    ] {
        if candidate.is_empty()
            || git(
                root,
                &["rev-parse", "--verify", &format!("{candidate}^{{commit}}")],
            )
            .is_empty()
        {
            continue;
        }
        if branch == candidate.strip_prefix("origin/").unwrap_or(candidate) {
            return None;
        }
        if !git(root, &["merge-base", candidate, "HEAD"]).is_empty() {
            return Some(candidate.to_owned());
        }
    }
    None
}
pub fn diff_files(root: &Path, base: Option<&str>) -> Result<(Vec<String>, String)> {
    let base = base.map(str::to_owned).or_else(|| default_base(root));
    if let Some(base) = base
        && let Ok(files) = changed_paths(root, &format!("{base}...HEAD"))
    {
        return Ok((files, base));
    }
    Ok((changed_paths(root, "HEAD")?, "working-tree".into()))
}
pub fn write_changed_files(root: &Path, previous: &str) -> Result<Value> {
    let files = changed_paths(root, &format!("{previous}..HEAD"))?;
    let output = crate::persistence::data_dir(&root).join("tmp/changed-files.json");
    fs::create_dir_all(output.parent().unwrap())?;
    write_json(&output, &json!(files))?;
    Ok(json!(output))
}
fn node_path(node: &Value, pruning: bool) -> Option<&str> {
    if let Some(path) = node["filePath"].as_str()
        && (!pruning || !path.is_empty())
    {
        return Some(path);
    }
    let mut parts = node["id"].as_str()?.split(':');
    let prefix = parts.next()?;
    if pruning
        && ![
            "file", "function", "class", "config", "document", "service", "table", "endpoint",
            "pipeline", "schema", "resource",
        ]
        .contains(&prefix)
    {
        return None;
    }
    parts.next()
}
pub fn prune_incremental_batch(root: &Path, changed: &Path) -> Result<Value> {
    let paths: BTreeSet<_> = crate::file_lists::read(changed)?.into_iter().collect();
    let graph = read_json(&crate::persistence::data_dir(&root).join("knowledge-graph.json"))?;
    let removed: BTreeSet<_> = array(&graph, "nodes")
        .iter()
        .filter(|n| node_path(n, true).is_some_and(|p| paths.contains(p)))
        .filter_map(|n| n["id"].as_str())
        .collect();
    let nodes: Vec<_> = array(&graph, "nodes")
        .iter()
        .filter(|n| n.is_object() && !n["id"].as_str().is_some_and(|id| removed.contains(id)))
        .collect();
    let edges: Vec<_> = array(&graph, "edges")
        .iter()
        .filter(|e| {
            e.is_object()
                && !["source", "target"]
                    .iter()
                    .any(|k| e[k].as_str().is_some_and(|id| removed.contains(id)))
        })
        .collect();
    let path = crate::persistence::data_dir(&root).join("intermediate/batch-existing.json");
    fs::create_dir_all(path.parent().unwrap())?;
    write_json(&path, &json!({"nodes":nodes,"edges":edges}))?;
    Ok(
        json!({"outputPath":path,"changedFiles":paths.len(),"removedNodes":removed.len(),"keptNodes":nodes.len(),"keptEdges":edges.len()}),
    )
}
pub fn diff_context(root: &Path, base: Option<&str>) -> Result<Value> {
    let graph = read_json(&crate::persistence::data_dir(&root).join("knowledge-graph.json"))?;
    let (files, label) = diff_files(root, base)?;
    let paths: BTreeSet<_> = files.iter().map(String::as_str).collect();
    let nodes: Vec<_> = array(&graph, "nodes")
        .iter()
        .filter(|n| node_path(n, false).is_some_and(|p| paths.contains(p)))
        .collect();
    let ids: BTreeSet<_> = nodes.iter().filter_map(|n| n["id"].as_str()).collect();
    let edges: Vec<_> = array(&graph, "edges")
        .iter()
        .filter(|e| {
            ["source", "target"]
                .iter()
                .any(|k| e[k].as_str().is_some_and(|id| ids.contains(id)))
        })
        .collect();
    let affected: BTreeSet<_> = edges
        .iter()
        .flat_map(|e| [e["source"].as_str(), e["target"].as_str()])
        .flatten()
        .filter(|id| !ids.contains(id))
        .collect();
    let affected_nodes: Vec<_> = array(&graph, "nodes")
        .iter()
        .filter(|n| n["id"].as_str().is_some_and(|id| affected.contains(id)))
        .collect();
    let layers: Vec<_> = array(&graph, "layers")
        .iter()
        .filter(|l| {
            array(l, "nodeIds").iter().any(|v| {
                v.as_str()
                    .is_some_and(|id| ids.contains(id) || affected.contains(id))
            })
        })
        .collect();
    let path = crate::persistence::data_dir(&root).join("diff-overlay.json");
    write_json(
        &path,
        &json!({"version":"1.0.0","baseBranch":label,"generatedAt":chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis,true),"changedFiles":files,"changedNodeIds":ids,"affectedNodeIds":affected}),
    )?;
    Ok(
        json!({"project":graph.get("project").cloned().unwrap_or(json!({})),"changedFiles":files,"changedNodes":nodes,"affectedNodes":affected_nodes,"edges":edges,"layers":layers,"overlayPath":path}),
    )
}
fn portable_path(path: &Path) -> String {
    path.components()
        .map(|component| component.as_os_str().to_string_lossy())
        .collect::<Vec<_>>()
        .join("/")
}
pub fn shallow_tree(root: &Path) -> Vec<String> {
    fn visit(root: &Path, directory: &Path, depth: usize, out: &mut Vec<String>) {
        let Ok(entries) = fs::read_dir(directory) else {
            return;
        };
        let mut entries: Vec<_> = entries.filter_map(std::result::Result::ok).collect();
        entries.sort_by_key(|e| e.file_name());
        for entry in entries {
            if out.len() >= 100 {
                return;
            }
            if ["node_modules", ".git", "dist"]
                .iter()
                .any(|s| entry.file_name() == *s)
            {
                continue;
            }
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_symlink() {
                continue;
            }
            if kind.is_file() {
                out.push(portable_path(entry.path().strip_prefix(root).unwrap()));
            } else if depth < 1 && kind.is_dir() {
                visit(root, &entry.path(), depth + 1, out);
            }
        }
    }
    let mut out = Vec::new();
    visit(root, root, 0, &mut out);
    out
}
fn read_first(root: &Path, names: &[&str], limit: usize) -> Result<String> {
    for name in names {
        let path = root.join(name);
        if path.is_file() {
            return Ok(String::from_utf8_lossy(&fs::read(path)?)
                .chars()
                .take(limit)
                .collect());
        }
    }
    Ok(String::new())
}
fn entry_point(root: &Path) -> Option<String> {
    for name in [
        "src/index.ts",
        "src/main.ts",
        "src/App.tsx",
        "index.js",
        "main.py",
        "manage.py",
        "app.py",
        "wsgi.py",
        "asgi.py",
        "run.py",
        "__main__.py",
        "src/main.rs",
        "src/lib.rs",
        "Program.cs",
        "config.ru",
        "index.php",
    ] {
        if root.join(name).is_file() {
            return Some(name.into());
        }
    }
    for (directory, java) in [("cmd", false), ("src/main/java", true)] {
        let mut matches: Vec<_> = walkdir::WalkDir::new(root.join(directory))
            .follow_links(false)
            .max_depth(if java { usize::MAX } else { 2 })
            .into_iter()
            .filter_map(std::result::Result::ok)
            .filter(|e| {
                e.file_type().is_file()
                    && e.file_name() == if java { "Application.java" } else { "main.go" }
                    && (java || e.depth() == 2)
            })
            .map(|e| portable_path(e.path().strip_prefix(root).unwrap()))
            .collect();
        matches.sort();
        if let Some(path) = matches.into_iter().next() {
            return Some(path);
        }
    }
    None
}
pub fn capture_project_context(root: &Path) -> Result<Value> {
    if !root.is_dir() {
        return Err(Error::Invalid(format!(
            "Not a directory: {}",
            root.display()
        )));
    }
    let payload = json!({"readmeContent":read_first(root,&["README.md","README.rst","readme.md"],3000)?,
        "manifestContent":read_first(root,&["package.json","pyproject.toml","Cargo.toml","go.mod","pom.xml"],usize::MAX)?,
        "dirTree":shallow_tree(root),"entryPoint":entry_point(root)});
    let path = crate::persistence::data_dir(&root).join("intermediate/project-context.json");
    fs::create_dir_all(path.parent().unwrap())?;
    write_json(&path, &payload)?;
    Ok(payload)
}
pub fn save_knowledge_graph(root: &Path) -> Result<Value> {
    let dir = crate::persistence::data_dir(&root);
    let graph = read_json(&dir.join("intermediate/assembled-graph.json"))?;
    let path = dir.join("knowledge-graph.json");
    write_json(&path, &graph)?;
    let nodes: Vec<_> = array(&graph, "nodes")
        .iter()
        .filter(|n| n.is_object())
        .collect();
    let edges: Vec<_> = array(&graph, "edges")
        .iter()
        .filter(|n| n.is_object())
        .collect();
    fn counts(items: &[&Value]) -> BTreeMap<String, usize> {
        let mut result = BTreeMap::new();
        for item in items {
            *result
                .entry(item["type"].as_str().unwrap_or("unknown").to_owned())
                .or_default() += 1;
        }
        result
    }
    let paths: BTreeSet<_> = nodes
        .iter()
        .filter_map(|n| n["filePath"].as_str().filter(|s| !s.is_empty()))
        .collect();
    let layers: Vec<_> = array(&graph, "layers")
        .iter()
        .filter(|l| l.is_object())
        .map(|l| json!({"id":l["id"],"name":l["name"],"nodeCount":array(l,"nodeIds").len()}))
        .collect();
    let summary = json!({"outputPath":path,"project":graph.get("project").cloned().unwrap_or(json!({})),"analyzedFiles":paths.len(),"totalNodes":nodes.len(),"nodesByType":counts(&nodes),"totalEdges":edges.len(),"edgesByType":counts(&edges),"layers":layers});
    write_json(&dir.join("intermediate/save-summary.json"), &summary)?;
    Ok(summary)
}
