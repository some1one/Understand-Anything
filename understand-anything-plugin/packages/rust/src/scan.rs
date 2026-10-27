//! Project enumeration, scanner detection, and ignore precedence.
use crate::{Error, Result, tables};
use ignore::gitignore::{Gitignore, GitignoreBuilder};
use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
pub fn extension(path: &str) -> String {
    let base = path.rsplit('/').next().unwrap_or(path);
    match base.rfind('.') {
        Some(i) if i > 0 => base[i..].to_lowercase(),
        _ => String::new(),
    }
}
fn dotkey(base: &str) -> String {
    if !base.starts_with('.') {
        return String::new();
    }
    format!(
        ".{}",
        base[1..]
            .chars()
            .take_while(|c| c.is_alphanumeric())
            .collect::<String>()
    )
    .to_lowercase()
}
pub fn detect_language(path: &str) -> String {
    let base = path.rsplit('/').next().unwrap_or(path);
    if base == "Dockerfile" || base.starts_with("Dockerfile.") {
        return "dockerfile".into();
    }
    let table = &tables()["languages"];
    let dot = dotkey(base);
    let ext = extension(path);
    if let Some(v) = table["LANGUAGE_BY_EXT"][&dot].as_str() {
        return v.into();
    }
    if !ext.is_empty() {
        return table["LANGUAGE_BY_EXT"][&ext]
            .as_str()
            .unwrap_or(&ext[1..])
            .into();
    }
    table["LANGUAGE_BY_FILENAME"][base]
        .as_str()
        .unwrap_or("unknown")
        .into()
}
pub fn detect_category(path: &str) -> String {
    let base = path.rsplit('/').next().unwrap_or(path);
    if base == "LICENSE" {
        return "code".into();
    }
    let table = &tables()["languages"];
    if crate::strings(&table["INFRA_FILENAMES"])
        .iter()
        .any(|v| v == base)
        || base.starts_with("Dockerfile.")
        || base.starts_with("docker-compose.")
        || ["compose.yml", "compose.yaml"].contains(&base)
        || path.starts_with(".github/workflows/")
        || path.starts_with(".circleci/")
        || path
            .split('/')
            .take(path.split('/').count().saturating_sub(1))
            .any(|p| ["k8s", "kubernetes"].contains(&p))
        || [".k8s.yml", ".k8s.yaml"]
            .iter()
            .any(|s| base.to_lowercase().ends_with(s))
    {
        return "infra".into();
    }
    let ext = extension(path);
    table["CATEGORY_BY_EXT"][&ext]
        .as_str()
        .or_else(|| table["CATEGORY_BY_EXT"][dotkey(base)].as_str())
        .unwrap_or("code")
        .into()
}
pub fn estimate_complexity(count: usize) -> &'static str {
    match count {
        0..=30 => "small",
        31..=150 => "moderate",
        151..=500 => "large",
        _ => "very-large",
    }
}
#[derive(Debug)]
pub struct IgnoreFilter {
    inner: Vec<Gitignore>,
}
impl IgnoreFilter {
    pub fn new(patterns: &[String]) -> Result<Self> {
        let mut inner = vec![];
        for line in patterns {
            let mut builder = GitignoreBuilder::new("");
            builder
                .add_line(None, line)
                .map_err(|e| Error::Invalid(e.to_string()))?;
            inner.push(builder.build().map_err(|e| Error::Invalid(e.to_string()))?);
        }
        Ok(Self { inner })
    }
    pub fn is_ignored(&self, path: &str) -> bool {
        self.inner
            .iter()
            .filter_map(|rule| {
                let matched = rule.matched_path_or_any_parents(path, false);
                if matched.is_none() {
                    None
                } else {
                    Some(matched.is_ignore())
                }
            })
            .next_back()
            .unwrap_or(false)
    }
}
pub fn default_patterns() -> Vec<String> {
    let mut patterns = crate::strings(&tables()["languages"]["DEFAULT_IGNORE_PATTERNS"]);
    patterns.extend([".ua/".into(), ".understand-anything/".into()]);
    patterns
}
pub fn create_ignore_filter(root: &Path) -> Result<IgnoreFilter> {
    create_ignore_filter_with_patterns(root, &[])
}
/// Invocation patterns are last, after defaults and both user ignore files.
pub fn create_ignore_filter_with_patterns(root: &Path, extra: &[String]) -> Result<IgnoreFilter> {
    let mut patterns = default_patterns();
    for p in [
        crate::persistence::data_dir(root).join(".uaignore"),
        root.join(".uaignore"),
    ] {
        if let Ok(text) = fs::read_to_string(p) {
            patterns.extend(text.lines().map(str::to_owned));
        }
    }
    patterns.extend_from_slice(extra);
    IgnoreFilter::new(&patterns)
}
pub fn enumerate_files(root: &Path) -> Vec<String> {
    enumerate_files_with_failures(root, &mut vec![])
}
fn enumerate_files_with_failures(root: &Path, failures: &mut Vec<Value>) -> Vec<String> {
    if let Ok(output) = Command::new("git")
        .args(["ls-files", "-z", "-co", "--exclude-standard"])
        .current_dir(root)
        .output()
        && output.status.success()
    {
        return String::from_utf8_lossy(&output.stdout)
            .split('\0')
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .collect();
    }
    let hard = ["node_modules", ".git", ".svn", ".hg", "__pycache__"];
    walkdir::WalkDir::new(root)
        .sort_by_file_name()
        .into_iter()
        .filter_entry(|e| {
            e.depth() == 0
                || !e.file_type().is_dir()
                || !hard.contains(&e.file_name().to_string_lossy().as_ref())
        })
        .filter_map(|entry| match entry {
            Ok(entry) => Some(entry),
            Err(error) => {
                failures.push(json!({"path":error.path().map(|p| p.to_string_lossy()),"stage":"enumeration","message":error.to_string()}));
                None
            }
        })
        .filter(|e| e.file_type().is_file())
        .filter_map(|e| {
            e.path()
                .strip_prefix(root)
                .ok()
                .map(|p| p.to_string_lossy().into_owned())
        })
        .collect()
}
pub fn scan_project(root: &Path) -> Result<Value> {
    scan_project_with_patterns(root, &[])
}
pub fn scan_project_with_patterns(root: &Path, extra: &[String]) -> Result<Value> {
    let combined = create_ignore_filter_with_patterns(root, extra)?;
    let defaults = IgnoreFilter::new(&default_patterns())?;
    let has_user = root.join(".uaignore").exists()
        || crate::persistence::data_dir(&root)
            .join(".uaignore")
            .exists();
    let mut filtered = 0;
    let mut files = vec![];
    let mut failures = vec![];
    for p in enumerate_files_with_failures(root, &mut failures) {
        if combined.is_ignored(&p) {
            if (has_user || !extra.is_empty()) && !defaults.is_ignored(&p) {
                filtered += 1;
            }
            continue;
        }
        if [".ps1", ".psm1", ".psd1", ".bat", ".cmd"].contains(&extension(&p).as_str()) {
            continue;
        }
        let path = root.join(&p);
        match fs::metadata(&path) {
            Ok(metadata) if metadata.is_file() => {},
            Ok(_) => continue,
            Err(error) => {
                failures.push(json!({"path":p,"stage":"file-stat","message":error.to_string()}));
                continue;
            }
        }
        match fs::read(path) {
            Ok(bytes) => files.push(json!({"path":p,"language":detect_language(&p),"sizeLines":bytes.iter().filter(|b| **b==b'\n').count(),"fileCategory":detect_category(&p)})),
            Err(e) => {
                failures.push(json!({"path":p,"stage":"file-read","message":e.to_string()}));
                eprintln!("Warning: scan-project: {p} — line count failed ({e}) — file skipped from output");
            },
        }
    }
    files.sort_by(|a, b| a["path"].as_str().cmp(&b["path"].as_str()));
    let mut categories = serde_json::Map::new();
    let mut languages = serde_json::Map::new();
    for f in &files {
        for (map, field) in [
            (&mut categories, "fileCategory"),
            (&mut languages, "language"),
        ] {
            let entry = map.entry(f[field].as_str().unwrap()).or_insert(json!(0));
            *entry = json!(entry.as_u64().unwrap() + 1);
        }
    }
    let mut result = json!({"scriptCompleted":true,"totalFiles":files.len(),"filteredByIgnore":filtered,"estimatedComplexity":estimate_complexity(files.len()),"stats":{"filesScanned":files.len(),"byCategory":categories,"byLanguage":languages},"files":files});
    if !extra.is_empty() { result["excludePatterns"] = json!(extra); }
    if !failures.is_empty() {
        result["failures"] = json!(failures);
    }
    Ok(result)
}
