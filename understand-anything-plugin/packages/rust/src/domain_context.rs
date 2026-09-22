//! Bounded lightweight scanner for domain-analysis context.
use crate::{Result, strings};
use regex::{Regex, RegexBuilder};
use serde_json::{Value, json};
use std::{fs, path::Path, sync::OnceLock};
fn tables() -> &'static Value {
    static T: OnceLock<Value> = OnceLock::new();
    T.get_or_init(|| serde_json::from_str(include_str!("../reference/domain_tables.json")).unwrap())
}
fn text(path: &Path) -> Option<String> {
    fs::read(path).ok().map(|b| {
        String::from_utf8_lossy(&b)
            .replace("\r\n", "\n")
            .replace('\r', "\n")
    })
}
fn prefix(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}
pub fn ascii_json(v: &Value) -> Result<String> {
    let raw = serde_json::to_string_pretty(v)?;
    let mut out = String::new();
    for c in raw.chars() {
        if c as u32 >= 127 {
            for unit in c.encode_utf16(&mut [0; 2]) {
                out.push_str(&format!("\\u{unit:04x}"));
            }
        } else {
            out.push(c);
        }
    }
    Ok(out)
}
pub fn parse_gitignore(root: &Path) -> Vec<Regex> {
    let Some(raw) = text(&root.join(".gitignore")) else {
        return vec![];
    };
    raw.lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                return None;
            }
            let mut pattern = line
                .replace('.', "\\.")
                .replace("**/", "(.*/)?")
                .replace('*', "[^/]*")
                .replace('?', "[^/]");
            if line.ends_with('/') {
                pattern = format!("{}(/|$)", pattern.trim_end_matches('/'));
            }
            match Regex::new(&pattern) {
                Ok(r) => Some(r),
                Err(e) => {
                    eprintln!("Warning: skipping invalid gitignore pattern '{line}': {e}");
                    None
                }
            }
        })
        .collect()
}
pub fn is_ignored(path: &str, patterns: &[Regex]) -> bool {
    patterns.iter().any(|r| r.is_match(path))
}
pub fn scan_file_tree(root: &Path, patterns: &[Regex], max_depth: usize) -> Vec<String> {
    fn walk(
        root: &Path,
        dir: &Path,
        depth: usize,
        max_depth: usize,
        patterns: &[Regex],
        out: &mut Vec<String>,
    ) {
        if depth > max_depth || out.len() >= 5000 {
            return;
        }
        let Ok(entries) = fs::read_dir(dir) else {
            return;
        };
        let mut entries: Vec<_> = entries.filter_map(|e| e.ok()).collect();
        entries.sort_by_key(|e| {
            (
                !e.path().is_dir(),
                e.file_name().to_string_lossy().to_lowercase(),
            )
        });
        let skip = strings(&tables()["SKIP_DIRS"]);
        let exts = strings(&tables()["SOURCE_EXTENSIONS"]);
        let mut count = 0;
        for e in entries {
            if out.len() >= 5000 {
                break;
            }
            if e.file_type().is_ok_and(|t| t.is_symlink()) {
                continue;
            }
            let p = e.path();
            let rel = p.strip_prefix(root).unwrap().to_string_lossy().to_string();
            if p.is_dir() {
                if !skip.contains(&e.file_name().to_string_lossy().to_string())
                    && !is_ignored(&format!("{rel}/"), patterns)
                {
                    walk(root, &p, depth + 1, max_depth, patterns, out);
                }
            } else if p.is_file() {
                if count >= 50 {
                    break;
                }
                let ext = p
                    .extension()
                    .map(|s| format!(".{}", s.to_string_lossy()))
                    .unwrap_or_default();
                if exts.contains(&ext) && !is_ignored(&rel, patterns) {
                    out.push(rel);
                    count += 1;
                }
            }
        }
    }
    let mut out = vec![];
    walk(root, root, 0, max_depth, patterns, &mut out);
    out
}
pub fn detect_entry_points(root: &Path, paths: &[String]) -> Vec<Value> {
    let skip = Regex::new(
        r"(?:\.test\.|\.spec\.|__tests__|_test\.py|test_\w+\.py|extract-domain-context\.py)",
    )
    .unwrap();
    let patterns: Vec<_> = tables()["patterns"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| {
            let f = v["flags"].as_u64().unwrap();
            (
                v,
                RegexBuilder::new(v["regex"].as_str().unwrap())
                    .case_insensitive(f & 2 != 0)
                    .multi_line(f & 8 != 0)
                    .build()
                    .unwrap(),
            )
        })
        .collect();
    let mut out = vec![];
    for path in paths {
        if out.len() >= 200 {
            break;
        }
        if skip.is_match(path) {
            continue;
        }
        let Some(content) = text(&root.join(path)) else {
            continue;
        };
        let lines: Vec<_> = content.lines().collect();
        for (v, r) in &patterns {
            for m in r.find_iter(&content) {
                let start = content[..m.start()].bytes().filter(|&b| b == b'\n').count();
                let snippet = lines
                    .iter()
                    .skip(start)
                    .take(5)
                    .copied()
                    .collect::<Vec<_>>()
                    .join("\n");
                out.push(json!({"file":path,"line":start+1,"type":v["type"],"description":v["description"],"match":prefix(m.as_str(),120),"snippet":prefix(&snippet,300)}));
                if out.len() >= 200 {
                    break;
                }
            }
            if out.len() >= 200 {
                break;
            }
        }
    }
    out
}
pub fn extract_file_signatures(root: &Path, paths: &[String]) -> Vec<Value> {
    let keywords = [
        "controller",
        "service",
        "handler",
        "router",
        "route",
        "api",
        "model",
        "entity",
        "repository",
        "usecase",
        "use_case",
        "command",
        "query",
        "event",
        "subscriber",
        "listener",
        "middleware",
        "guard",
        "interceptor",
        "resolver",
        "workflow",
        "flow",
        "process",
        "pipeline",
        "job",
        "task",
    ];
    let mut paths = paths.to_vec();
    paths.sort_by_key(|p| {
        std::cmp::Reverse(
            keywords
                .iter()
                .filter(|kw| p.to_lowercase().contains(**kw))
                .count(),
        )
    });
    let js=Regex::new(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+(\w+)").unwrap();
    let py = Regex::new(r"(?m)^(?:def|class)\s+(\w+)").unwrap();
    let imports =
        Regex::new(r#"(?:import\s+.*?from\s+['"]([^'"]+)['"]|from\s+([\w.]+)\s+import)"#).unwrap();
    paths.iter().take(40).filter_map(|path|{let content=text(&root.join(path))?;let truncated=content.lines().take(80).collect::<Vec<_>>().join("\n");let mut exports:Vec<_>=js.captures_iter(&truncated).map(|c|c[1].to_owned()).collect();if exports.is_empty(){exports=py.captures_iter(&truncated).map(|c|c[1].to_owned()).collect();}exports.truncate(20);let imports:Vec<_>=imports.captures_iter(&truncated).take(20).map(|c|c.get(1).or_else(||c.get(2)).unwrap().as_str().to_owned()).collect();Some(json!({"file":path,"exports":exports,"imports":imports,"lines":content.lines().count(),"preview":prefix(&truncated,500)}))}).collect()
}
pub fn extract_metadata(root: &Path) -> Value {
    let mut out = json!({});
    for file in strings(&tables()["METADATA_FILES"]) {
        let Some(content) = text(&root.join(&file)) else {
            continue;
        };
        if file == "package.json" {
            out[&file] = match serde_json::from_str::<Value>(&content) {
                Ok(pkg) => {
                    let keys = |key: &str| {
                        pkg[key]
                            .as_object()
                            .map(|o| o.keys().cloned().collect::<Vec<_>>())
                            .unwrap_or_default()
                    };
                    json!({"name":pkg["name"],"description":pkg["description"],"scripts":keys("scripts"),"dependencies":keys("dependencies"),"devDependencies":keys("devDependencies")})
                }
                Err(_) => json!(prefix(&content, 500)),
            };
        } else if file == "README" || [".md", ".rst", ".txt"].iter().any(|s| file.ends_with(s)) {
            out[&file] = json!(prefix(&content, 2000));
        } else if [
            ".toml", ".cfg", ".mod", ".json", ".yml", ".yaml", ".xml", ".gradle",
        ]
        .iter()
        .any(|s| file.ends_with(s))
        {
            out[&file] = json!(prefix(&content, 1000));
        }
    }
    out
}
pub fn truncate_to_fit(context: &mut Value) -> Result<()> {
    if ascii_json(context)?.len() <= 512 * 1024 {
        return Ok(());
    }
    if let Some(a) = context["fileTree"].as_array_mut() {
        a.truncate(200);
    }
    if ascii_json(context)?.len() <= 512 * 1024 {
        return Ok(());
    }
    if let Some(a) = context["fileSignatures"].as_array_mut() {
        for v in a {
            v["preview"] = json!(prefix(v["preview"].as_str().unwrap_or(""), 200));
        }
    }
    if ascii_json(context)?.len() <= 512 * 1024 {
        return Ok(());
    }
    if let Some(a) = context["entryPoints"].as_array_mut() {
        for v in a {
            v["snippet"] = json!(prefix(v["snippet"].as_str().unwrap_or(""), 100));
        }
    }
    if ascii_json(context)?.len() <= 512 * 1024 {
        return Ok(());
    }
    if let Some(a) = context["fileSignatures"].as_array_mut() {
        a.truncate(20);
    }
    if let Some(a) = context["entryPoints"].as_array_mut() {
        a.truncate(100);
    }
    Ok(())
}
pub fn extract(root: &Path) -> Result<Value> {
    let paths = scan_file_tree(root, &parse_gitignore(root), 6);
    let mut context = json!({"projectRoot":root,"fileCount":paths.len(),"fileTree":paths,"entryPoints":detect_entry_points(root,&paths),"fileSignatures":extract_file_signatures(root,&paths),"metadata":extract_metadata(root)});
    truncate_to_fit(&mut context)?;
    Ok(context)
}
