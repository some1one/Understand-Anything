//! Language-specific project-internal import resolution.
use crate::{Error, Result, strings};
use regex::Regex;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};
pub fn to_posix(s: &str) -> String {
    // Backslashes are filename characters on Unix, not directory separators.
    // Namespace separators (for example PHP FQNs) are converted explicitly by
    // their language resolver, independently of filesystem path handling.
    s.split(|ch| ch == '/' || (std::path::MAIN_SEPARATOR == '\\' && ch == '\\'))
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("/")
}
pub fn dir_of(s: &str) -> &str {
    s.rsplit_once('/').map_or("", |p| p.0)
}
pub fn resolve_relative(dir: &str, rel: &str) -> String {
    let mut stack = vec![];
    for part in dir.split('/').chain(rel.split('/')) {
        match part {
            "" | "." => {}
            ".." => {
                if stack.pop().is_none() {
                    return String::new();
                }
            }
            _ => stack.push(part),
        }
    }
    stack.join("/")
}
pub fn posix_normalize(s: &str) -> String {
    let leading = s.starts_with("..");
    let mut stack = vec![];
    for part in s.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                if stack.last().is_some_and(|p| *p != "..") {
                    stack.pop();
                } else {
                    stack.push(part);
                }
            }
            _ => stack.push(part),
        }
    }
    let out = stack.join("/");
    if leading && !out.starts_with("..") {
        if out.is_empty() {
            "..".into()
        } else {
            format!("../{out}")
        }
    } else {
        out
    }
}
fn join(parts: &[&str]) -> String {
    posix_normalize(
        &parts
            .iter()
            .copied()
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("/"),
    )
}
fn rx(s: &str) -> Regex {
    Regex::new(s).unwrap()
}
// JSONC comments and trailing commas are syntax only outside quoted strings.
fn normalize_jsonc(raw: &str) -> Option<String> {
    let bytes = raw.trim_start_matches('\u{feff}').as_bytes();
    let mut clean = Vec::with_capacity(bytes.len());
    let (mut quoted, mut escaped, mut i) = (false, false, 0);
    while i < bytes.len() {
        let ch = bytes[i];
        if quoted {
            clean.push(ch);
            if escaped {
                escaped = false;
            } else if ch == b'\\' {
                escaped = true;
            } else if ch == b'"' {
                quoted = false;
            }
        } else if ch == b'"' {
            quoted = true;
            clean.push(ch);
        } else if ch == b'/' && bytes.get(i + 1) == Some(&b'/') {
            clean.push(b' ');
            i += 2;
            while i < bytes.len() && bytes[i] != b'\n' && bytes[i] != b'\r' {
                i += 1;
            }
            continue;
        } else if ch == b'/' && bytes.get(i + 1) == Some(&b'*') {
            clean.push(b' ');
            i += 2;
            while i + 1 < bytes.len() && !(bytes[i] == b'*' && bytes[i + 1] == b'/') {
                i += 1;
            }
            if i + 1 >= bytes.len() {
                return None;
            }
            i += 2;
            continue;
        } else {
            clean.push(ch);
        }
        i += 1;
    }
    let mut output = Vec::with_capacity(clean.len());
    quoted = false;
    escaped = false;
    for (i, &ch) in clean.iter().enumerate() {
        if quoted {
            if escaped {
                escaped = false;
            } else if ch == b'\\' {
                escaped = true;
            } else if ch == b'"' {
                quoted = false;
            }
        } else if ch == b'"' {
            quoted = true;
        } else if ch == b',' {
            let next = clean[i + 1..].iter().find(|ch| !ch.is_ascii_whitespace());
            if matches!(next, Some(b'}' | b']')) {
                continue;
            }
        }
        output.push(ch);
    }
    String::from_utf8(output).ok()
}

pub fn parse_tsconfig_text(raw: &str) -> Option<Value> {
    let p: Value = serde_json::from_str(&normalize_jsonc(raw)?).ok()?;
    let co = &p["compilerOptions"];
    let paths: serde_json::Map<_, _> = co["paths"]
        .as_object()
        .into_iter()
        .flatten()
        .filter(|(_, v)| v.is_array())
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    Some(json!({"baseUrl":co.get("baseUrl").cloned().unwrap_or(json!(".")),"paths":paths}))
}
pub fn parse_composer_autoload_text(raw: &str) -> Option<Value> {
    let p: Value = serde_json::from_str(raw).ok()?;
    let mut out = json!({});
    if let Some(psr) = p["autoload"]["psr-4"].as_object() {
        for (prefix, target) in psr {
            let values = if target.is_array() {
                target.as_array().unwrap().clone()
            } else {
                vec![target.clone()]
            };
            let dirs: Vec<_> = values
                .iter()
                .filter_map(Value::as_str)
                .map(to_posix)
                .collect();
            let prefix = if prefix.is_empty() || prefix.ends_with('\\') {
                prefix.clone()
            } else {
                format!("{prefix}\\")
            };
            out[prefix] = json!(dirs);
        }
    }
    Some(out)
}
pub fn find_nearest_config_dir<'a>(
    start: &str,
    configs: &'a BTreeMap<String, Value>,
) -> Option<&'a str> {
    let mut dir = start;
    loop {
        if let Some((key, _)) = configs.get_key_value(dir) {
            return Some(key);
        }
        if dir.is_empty() {
            return None;
        }
        dir = dir_of(dir);
    }
}
pub struct ResolutionContext {
    pub file_set: BTreeSet<String>,
    pub ts_configs: BTreeMap<String, Value>,
    pub go_modules: BTreeMap<String, Value>,
    pub php_autoloads: BTreeMap<String, Value>,
    pub go_files_by_dir: BTreeMap<String, Vec<String>>,
    pub suffix_index: BTreeMap<String, Vec<String>>,
    failures: Vec<String>,
    warned_go: BTreeSet<String>,
    warned_rust: BTreeSet<String>,
}
impl ResolutionContext {
    pub fn new(root: &Path, files: &[Value]) -> Self {
        let mut c = Self {
            file_set: files
                .iter()
                .filter_map(|f| f["path"].as_str())
                .map(to_posix)
                .collect(),
            ts_configs: BTreeMap::new(),
            go_modules: BTreeMap::new(),
            php_autoloads: BTreeMap::new(),
            go_files_by_dir: BTreeMap::new(),
            suffix_index: BTreeMap::new(),
            failures: Vec::new(),
            warned_go: BTreeSet::new(),
            warned_rust: BTreeSet::new(),
        };
        for name in ["tsconfig.json", "go.mod", "composer.json"] {
            for f in files {
                let p = to_posix(f["path"].as_str().unwrap_or(""));
                if p.rsplit('/').next() != Some(name) {
                    continue;
                }
                let abs = root.join(&p);
                let raw = match fs::read_to_string(&abs) {
                    Ok(s) => s,
                    Err(e) => {
                        c.failures.push(format!("{p}: resolver configuration read failed: {e}"));
                        continue;
                    }
                };
                let parsed = match name {
                    "tsconfig.json" => parse_tsconfig_text(&raw),
                    "composer.json" => parse_composer_autoload_text(&raw),
                    _ => raw
                        .lines()
                        .map(|l| l.split("//").next().unwrap_or("").trim())
                        .find_map(|l| l.strip_prefix("module ").map(str::trim))
                        .filter(|s| !s.is_empty())
                        .map(|s| json!(s)),
                };
                if let Some(config) = parsed {
                    let target = match name {
                        "tsconfig.json" => &mut c.ts_configs,
                        "composer.json" => &mut c.php_autoloads,
                        _ => &mut c.go_modules,
                    };
                    target.insert(dir_of(&p).into(), config);
                } else {
                    c.failures.push(format!("{p}: resolver configuration parse failed"));
                }
            }
        }
        for f in files {
            let p = to_posix(f["path"].as_str().unwrap_or(""));
            if p.ends_with(".go") {
                c.go_files_by_dir
                    .entry(dir_of(&p).into())
                    .or_default()
                    .push(p.clone());
            }
            if [".java", ".kt", ".cs"].iter().any(|e| p.ends_with(e)) {
                let parts: Vec<_> = p.split('/').collect();
                for i in 0..parts.len() {
                    c.suffix_index
                        .entry(parts[i..].join("/"))
                        .or_default()
                        .push(p.clone());
                }
            }
        }
        for values in c
            .go_files_by_dir
            .values_mut()
            .chain(c.suffix_index.values_mut())
        {
            values.sort();
        }
        c
    }
}
pub fn probe_with_extensions(base: &str, files: &BTreeSet<String>) -> Option<String> {
    if base.is_empty() {
        return None;
    }
    if files.contains(base) {
        return Some(base.into());
    }
    for (ext, rewrites) in [
        (".js", vec![".ts", ".tsx", ".js", ".jsx"]),
        (".jsx", vec![".tsx", ".jsx"]),
        (".mjs", vec![".mts", ".mjs", ".ts"]),
        (".cjs", vec![".cts", ".cjs", ".ts"]),
    ] {
        if let Some(stem) = base.strip_suffix(ext) {
            return rewrites
                .iter()
                .map(|e| format!("{stem}{e}"))
                .find(|p| files.contains(p));
        }
    }
    [
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        "/index.ts",
        "/index.tsx",
        "/index.js",
        "/index.jsx",
    ]
    .iter()
    .map(|e| format!("{base}{e}"))
    .find(|p| files.contains(p))
}
pub fn match_ts_alias<'a>(alias: &str, src: &'a str) -> Option<&'a str> {
    if let Some((pre, suf)) = alias.split_once('*') {
        if src.starts_with(pre) && src.ends_with(suf) && src.len() >= pre.len() + suf.len() {
            Some(&src[pre.len()..src.len() - suf.len()])
        } else {
            None
        }
    } else if alias == src {
        Some("")
    } else {
        None
    }
}
pub fn apply_ts_alias(target: &str, wild: &str) -> String {
    target.replacen('*', wild, 1)
}
pub fn resolve_ts_js_import(src: &str, path: &str, c: &ResolutionContext) -> Option<String> {
    let src = src.trim();
    if src.is_empty() {
        return None;
    }
    let dir = dir_of(path);
    if src.starts_with("./") || src.starts_with("../") {
        return probe_with_extensions(&resolve_relative(dir, src), &c.file_set);
    }
    let cfgdir = find_nearest_config_dir(dir, &c.ts_configs)?;
    let config = &c.ts_configs[cfgdir];
    if let Some(paths) = config["paths"].as_object() {
        for (alias, targets) in paths {
            if let Some(wild) = match_ts_alias(alias, src) {
                for target in strings(targets) {
                    let mapped = apply_ts_alias(&target, wild);
                    let base = config["baseUrl"].as_str().unwrap_or(".");
                    let norm = if [".", ""].contains(&base) {
                        String::new()
                    } else {
                        to_posix(base)
                    };
                    let rel = if norm.is_empty() {
                        mapped
                    } else {
                        join(&[&norm, &mapped])
                    };
                    let candidate = posix_normalize(&if cfgdir.is_empty() {
                        rel
                    } else {
                        join(&[cfgdir, &rel])
                    });
                    if !candidate.starts_with("..")
                        && let Some(p) = probe_with_extensions(&candidate, &c.file_set)
                    {
                        return Some(p);
                    }
                }
            }
        }
    }
    None
}
pub fn strip_js_like_comments(s: &str) -> String {
    rx(r"//[^\n]*")
        .replace_all(&rx(r"/\*[\s\S]*?\*/").replace_all(s, ""), "")
        .into_owned()
}
pub fn extract_require_sources(s: &str) -> Vec<String> {
    rx(r#"\brequire\(\s*(['"])([^'"`\n]+?)(['"])\s*\)"#)
        .captures_iter(&strip_js_like_comments(s))
        .filter(|c| c[1] == c[3])
        .map(|c| c[2].to_owned())
        .collect()
}
pub fn extract_kotlin_sources(s: &str) -> Vec<String> {
    rx(r"(?m)^\s*import\s+(\w+(?:\.\w+)*(?:\.\*)?)(?:\s+as\s+\w+)?\s*$")
        .captures_iter(s)
        .map(|c| c[1].to_owned())
        .collect()
}
pub fn extract_rust_mod_sources(s: &str) -> Vec<String> {
    rx(r"(?m)^\s*(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+(\w+)\s*;\s*$")
        .captures_iter(&strip_js_like_comments(s))
        .map(|c| format!("self::{}", &c[1]))
        .collect()
}
pub fn parse_ruby_imports(s: &str) -> Vec<Value> {
    let stripped = rx(r"#[^\n]*").replace_all(s, "");
    rx(r#"\b(require_relative|require)\s*\(?\s*(['"])([^'"`\n]+?)(['"])"#).captures_iter(&stripped).filter(|c|c[2]==c[4]).map(|c|json!({"kind":if &c[1]=="require_relative"{"relative"}else{"absolute"},"source":&c[3]})).collect()
}
fn python_submodules(base: &str, spec: &[String], c: &ResolutionContext) -> Vec<String> {
    spec.iter()
        .filter(|s| !s.is_empty() && *s != "*" && !s.contains('.'))
        .filter_map(|s| {
            let pre = if base.is_empty() {
                s.clone()
            } else {
                format!("{base}/{s}")
            };
            [format!("{pre}.py"), format!("{pre}/__init__.py")]
                .into_iter()
                .find(|p| c.file_set.contains(p))
        })
        .collect()
}
pub fn resolve_python_probe(parts: &[&str], spec: &[String], c: &ResolutionContext) -> Vec<String> {
    if parts.is_empty() {
        return vec![];
    }
    let base = parts.join("/");
    let p = format!("{base}.py");
    if c.file_set.contains(&p) {
        return vec![p];
    }
    let p = format!("{base}/__init__.py");
    if c.file_set.contains(&p) {
        let mut out = vec![p];
        out.extend(python_submodules(&base, spec, c));
        out
    } else {
        vec![]
    }
}
pub fn resolve_python_import(
    src: &str,
    spec: &[String],
    path: &str,
    c: &ResolutionContext,
) -> Vec<String> {
    let dots = src.chars().take_while(|&s| s == '.').count();
    let tail: Vec<_> = src[dots..].split('.').filter(|s| !s.is_empty()).collect();
    let dir: Vec<_> = dir_of(path).split('/').filter(|s| !s.is_empty()).collect();
    if dots > 0 {
        if dots - 1 > dir.len() {
            return vec![];
        }
        let mut base = dir[..dir.len() - (dots - 1)].to_vec();
        if tail.is_empty() {
            return python_submodules(&base.join("/"), spec, c);
        }
        base.extend(tail);
        return resolve_python_probe(&base, spec, c);
    }
    if tail.is_empty() {
        return vec![];
    }
    for i in (0..=dir.len()).rev() {
        let mut parts = dir[..i].to_vec();
        parts.extend(&tail);
        let out = resolve_python_probe(&parts, spec, c);
        if !out.is_empty() {
            return out;
        }
    }
    vec![]
}
pub fn resolve_ruby_import(imp: &Value, path: &str, c: &ResolutionContext) -> Vec<String> {
    let source = imp["source"].as_str().unwrap_or("");
    if source.is_empty() {
        return vec![];
    }
    let ext = if source.ends_with(".rb") {
        source.into()
    } else {
        format!("{source}.rb")
    };
    let probes = if imp["kind"] == "relative" {
        vec![resolve_relative(dir_of(path), &ext)]
    } else {
        vec![format!("lib/{ext}"), format!("app/{ext}"), ext]
    };
    probes
        .into_iter()
        .find(|p| c.file_set.contains(p))
        .into_iter()
        .collect()
}
pub fn probe_rust_module(base: &str, files: &BTreeSet<String>) -> Option<String> {
    if base.is_empty() {
        return None;
    }
    [format!("{base}.rs"), format!("{base}/mod.rs")]
        .into_iter()
        .find(|p| files.contains(p))
}
pub fn find_rust_crate_src(dir: &str, files: &BTreeSet<String>) -> Option<String> {
    let parts: Vec<_> = dir.split('/').filter(|s| !s.is_empty()).collect();
    for i in (0..=parts.len()).rev() {
        let src = if i == 0 {
            "src".into()
        } else {
            format!("{}/src", parts[..i].join("/"))
        };
        if files.contains(&format!("{src}/lib.rs")) || files.contains(&format!("{src}/main.rs")) {
            return Some(src);
        }
    }
    None
}
pub fn resolve_import(imp: &Value, file: &Value, c: &mut ResolutionContext) -> Vec<String> {
    let Some(src) = imp["source"].as_str() else {
        return vec![];
    };
    let path = to_posix(file["path"].as_str().unwrap_or(""));
    let lang = file["language"].as_str().unwrap_or("");
    match lang {
        "typescript" | "javascript" | "tsx" | "jsx" | "vue" => {
            resolve_ts_js_import(src, &path, c).into_iter().collect()
        }
        "python" => resolve_python_import(src, &strings(&imp["specifiers"]), &path, c),
        "go" => {
            let src = src.trim();
            if src.is_empty() {
                return vec![];
            }
            let Some(dir) = find_nearest_config_dir(dir_of(&path), &c.go_modules) else {
                if c.warned_go.insert(path.clone()) {
                    eprintln!(
                        "Warning: extract-import-map: Go file {path} has no ancestor go.mod — import {src} unresolvable — module-prefix imports skipped"
                    );
                }
                return vec![];
            };
            let module = c.go_modules[dir].as_str().unwrap_or("");
            let rest = if src == module {
                ""
            } else if let Some(r) = src.strip_prefix(&format!("{module}/")) {
                r
            } else {
                return vec![];
            };
            let target = if dir.is_empty() {
                to_posix(rest)
            } else if rest.is_empty() {
                dir.into()
            } else {
                format!("{dir}/{}", to_posix(rest))
            };
            c.go_files_by_dir.get(&target).cloned().unwrap_or_default()
        }
        "java" | "kotlin" | "csharp" => {
            let ext = match lang {
                "java" => ".java",
                "kotlin" => ".kt",
                _ => ".cs",
            };
            let suffix = format!(
                "{}{ext}",
                src.strip_suffix(".*").unwrap_or(src).replace('.', "/")
            );
            c.suffix_index.get(&suffix).cloned().unwrap_or_default()
        }
        "php" => {
            let fqn = src.strip_prefix('\\').unwrap_or(src);
            let Some(dir) = find_nearest_config_dir(dir_of(&path), &c.php_autoloads) else {
                return vec![];
            };
            let Some(map) = c.php_autoloads[dir].as_object() else {
                return vec![];
            };
            let Some((prefix, targets)) = map
                .iter()
                .filter(|(p, _)| fqn.starts_with(p.as_str()))
                .max_by_key(|(p, _)| p.len())
            else {
                return vec![];
            };
            let rel = fqn[prefix.len()..].replace('\\', "/");
            if rel.is_empty() {
                return vec![];
            }
            strings(targets)
                .iter()
                .map(|d| {
                    [dir, d, &format!("{rel}.php")]
                        .into_iter()
                        .filter(|s| !s.is_empty())
                        .collect::<Vec<_>>()
                        .join("/")
                })
                .find(|p| c.file_set.contains(p))
                .into_iter()
                .collect()
        }
        "rust" => {
            let segments: Vec<_> = src.trim().split("::").filter(|s| !s.is_empty()).collect();
            let Some(head) = segments.first() else {
                return vec![];
            };
            let dir = dir_of(&path);
            let base = match *head {
                "crate" => match find_rust_crate_src(dir, &c.file_set) {
                    Some(p) => p,
                    None => {
                        if c.warned_rust.insert(path.clone()) {
                            eprintln!(
                                "Warning: extract-import-map: Rust file {path} has 'use crate::' but no crate root (src/lib.rs or src/main.rs) found — crate-relative imports unresolved"
                            );
                        }
                        return vec![];
                    }
                },
                "super" => {
                    if dir.is_empty() {
                        return vec![];
                    }
                    dir_of(dir).into()
                }
                "self" => dir.into(),
                _ => return vec![],
            };
            for i in (1..segments.len()).rev() {
                let suffix = segments[1..=i].join("/");
                let p = if base.is_empty() {
                    suffix
                } else {
                    format!("{base}/{suffix}")
                };
                if let Some(found) = probe_rust_module(&p, &c.file_set) {
                    return vec![found];
                }
            }
            vec![]
        }
        "c" | "cpp" => {
            let src = to_posix(src.trim());
            if src.is_empty() {
                return vec![];
            }
            [
                resolve_relative(dir_of(&path), &src),
                format!("include/{src}"),
                format!("src/{src}"),
                src,
            ]
            .into_iter()
            .find(|p| !p.is_empty() && c.file_set.contains(p))
            .into_iter()
            .collect()
        }
        _ => vec![],
    }
}
/// Select source files without narrowing the inventory used for resolution.
pub fn select_analysis_files<'a>(
    files: &'a [Value],
    paths: Option<&Value>,
) -> Result<Vec<&'a Value>> {
    let Some(paths) = paths else {
        return Ok(files.iter().collect());
    };
    let paths = paths
        .as_array()
        .ok_or_else(|| Error::Invalid("analysisPaths must be an array".into()))?;
    let mut inventory = BTreeMap::new();
    for file in files {
        let path = file["path"]
            .as_str()
            .filter(|path| !path.is_empty())
            .ok_or_else(|| {
                Error::Invalid("every inventory entry must have a non-empty path".into())
            })?;
        if Path::new(path).is_absolute() || to_posix(path).split('/').any(|part| part == "..") {
            return Err(Error::Invalid(format!(
                "inventory path must be project-relative: {path}"
            )));
        }
        inventory.insert(to_posix(path), file);
    }
    let mut selected = vec![];
    let mut seen = BTreeSet::new();
    for value in paths {
        let path = value
            .as_str()
            .filter(|path| !path.is_empty())
            .ok_or_else(|| {
                Error::Invalid("every analysisPaths entry must be a non-empty string".into())
            })?;
        let normalized = to_posix(path);
        if Path::new(path).is_absolute()
            || normalized.is_empty()
            || normalized.split('/').any(|part| part == "..")
        {
            return Err(Error::Invalid(format!(
                "analysisPaths must stay inside projectRoot: {path}"
            )));
        }
        let file = inventory.get(&normalized).ok_or_else(|| {
            Error::Invalid(format!("analysisPaths entry is not in inventory: {path}"))
        })?;
        if seen.insert(normalized) {
            selected.push(*file);
        }
    }
    Ok(selected)
}

pub fn extract_import_map(input: &Value) -> Result<Value> {
    let root = input["projectRoot"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            Error::Invalid("Invalid input: must contain projectRoot and files array".into())
        })?;
    let files = input["files"].as_array().ok_or_else(|| {
        Error::Invalid("Invalid input: must contain projectRoot and files array".into())
    })?;
    let analysis_files = select_analysis_files(files, input.get("analysisPaths"))?;
    if analysis_files.is_empty() {
        return Ok(
            json!({"scriptCompleted":true,"stats":{"filesScanned":0,"filesWithImports":0,"totalEdges":0},"importMap":{}}),
        );
    }
    let mut c = ResolutionContext::new(Path::new(root), files);
    if !c.failures.is_empty() {
        return Err(Error::Invalid(format!(
            "Import extraction failed: {}", c.failures.join("; ")
        )));
    }
    let mut map = json!({});
    let mut count = 0;
    let mut edges = 0;
    for f in &analysis_files {
        let path = to_posix(f["path"].as_str().unwrap_or(""));
        map[&path] = json!([]);
        if f["fileCategory"] != "code" {
            continue;
        }
        let content = fs::read_to_string(Path::new(root).join(&path)).map_err(|e| {
            Error::Invalid(format!("Import extraction failed for {path} (read error: {e})"))
        })?;
        let content = content.replace("\r\n", "\n").replace('\r', "\n");
        let lang = f["language"].as_str().unwrap_or("");
        let mut resolved = BTreeSet::new();
        if lang == "ruby" {
            for imp in parse_ruby_imports(&content) {
                resolved.extend(resolve_ruby_import(&imp, &path, &c));
            }
        } else {
            let extraction = match lang {
                "tsx" | "jsx" | "vue" => "typescript",
                s => s,
            };
            // Unsupported languages have no structural import extractor. A supported
            // grammar failing to load, however, must never publish an empty map.
            if crate::parsers::LANGUAGES.contains(&extraction) {
                let imports = crate::structure::try_extract_import_sources(extraction, &content)
                    .map_err(|e| Error::Invalid(format!(
                        "Import extraction failed for {path} ({extraction} parser: {e})"
                    )))?;
                for imp in imports {
                    resolved.extend(resolve_import(&imp, f, &mut c));
                }
            }
            let extras = match lang {
                "typescript" | "javascript" | "tsx" | "jsx" | "vue" => {
                    extract_require_sources(&content)
                }
                "kotlin" => extract_kotlin_sources(&content),
                "rust" => extract_rust_mod_sources(&content),
                _ => vec![],
            };
            for source in extras {
                resolved.extend(resolve_import(
                    &json!({"source":source,"specifiers":[]}),
                    f,
                    &mut c,
                ));
            }
        }
        resolved.retain(|p| !p.is_empty() && c.file_set.contains(p));
        if !resolved.is_empty() {
            count += 1;
            edges += resolved.len();
        }
        map[path] = json!(resolved);
    }
    Ok(
        json!({"scriptCompleted":true,"stats":{"filesScanned":analysis_files.len(),"filesWithImports":count,"totalEdges":edges},"importMap":map}),
    )
}
