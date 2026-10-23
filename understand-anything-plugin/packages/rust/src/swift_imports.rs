//! Swift module inventory, including literal SwiftPM target paths.
use crate::imports::{dir_of, resolve_relative};
use regex::Regex;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

fn module_name(name: &str) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

// Preserve byte offsets while removing comments, and optionally string bodies.
fn code_text(raw: &str, mask_strings: bool) -> String {
    let bytes = raw.as_bytes();
    let mut out = bytes.to_vec();
    let (mut i, mut quoted, mut escaped, mut block) = (0, false, false, 0usize);
    while i < bytes.len() {
        if block > 0 {
            if bytes[i..].starts_with(b"/*") {
                block += 1;
                out[i..i + 2].fill(b' ');
                i += 2;
            } else if bytes[i..].starts_with(b"*/") {
                block -= 1;
                out[i..i + 2].fill(b' ');
                i += 2;
            } else {
                out[i] = b' ';
                i += 1;
            }
        } else if quoted {
            if mask_strings {
                out[i] = b' ';
            }
            if escaped {
                escaped = false;
            } else if bytes[i] == b'\\' {
                escaped = true;
            } else if bytes[i] == b'"' {
                quoted = false;
            }
            i += 1;
        } else if bytes[i..].starts_with(b"//") {
            while i < bytes.len() && bytes[i] != b'\n' {
                out[i] = b' ';
                i += 1;
            }
        } else if bytes[i..].starts_with(b"/*") {
            block = 1;
            out[i..i + 2].fill(b' ');
            i += 2;
        } else {
            if bytes[i] == b'"' {
                quoted = true;
                if mask_strings {
                    out[i] = b' ';
                }
            }
            i += 1;
        }
    }
    String::from_utf8(out).expect("only complete comment and string bytes are masked")
}

// This is a literal target reader, not an evaluator of arbitrary Swift code.
fn targets(raw: &str) -> Vec<(String, String)> {
    let clean = code_text(raw, false);
    let raw = clean.as_str();
    let call_sites = code_text(raw, true);
    let calls = Regex::new(r"\.(target|executableTarget|testTarget)\s*\(").unwrap();
    let literal = Regex::new(r#"^\s*(name|path)\s*:\s*"([^"\\]+)"\s*$"#).unwrap();
    let mut result = vec![];
    let mut end = 0;
    for call in calls.captures_iter(&call_sites) {
        let m = call.get(0).unwrap();
        if m.start() < end {
            continue;
        }
        let mut depth = 0;
        let mut quoted = false;
        let mut escaped = false;
        let mut start = m.end();
        let mut name = None;
        let mut path = None;
        for (offset, c) in raw[m.end()..].char_indices() {
            let i = m.end() + offset;
            if quoted {
                if escaped {
                    escaped = false;
                } else if c == '\\' {
                    escaped = true;
                } else if c == '"' {
                    quoted = false;
                }
                continue;
            }
            if c == '"' {
                quoted = true;
                continue;
            }
            if (c == ',' || c == ')') && depth == 0 {
                if let Some(value) = literal.captures(&raw[start..i]) {
                    match &value[1] {
                        "name" => name = Some(value[2].to_owned()),
                        "path" => path = Some(value[2].to_owned()),
                        _ => {}
                    }
                }
                start = i + 1;
                if c == ')' {
                    end = i + 1;
                    break;
                }
            } else if ['(', '[', '{'].contains(&c) {
                depth += 1;
            } else if [')', ']', '}'].contains(&c) {
                depth -= 1;
            }
        }
        if let Some(name) = name {
            let base = if &call[1] == "testTarget" {
                "Tests"
            } else {
                "Sources"
            };
            result.push((
                name.clone(),
                path.unwrap_or_else(|| format!("{base}/{name}")),
            ));
        }
    }
    result
}

pub(crate) fn build(
    root: &Path,
    files: &BTreeSet<String>,
    failures: &mut Vec<String>,
) -> BTreeMap<String, Vec<String>> {
    let mut declared = vec![];
    for p in files
        .iter()
        .filter(|p| p.rsplit('/').next() == Some("Package.swift"))
    {
        match fs::read_to_string(root.join(p)) {
            Ok(raw) => {
                for (name, path) in targets(&raw) {
                    let path = resolve_relative(dir_of(p), &path);
                    if !path.is_empty() {
                        declared.push((name, path));
                    }
                }
            }
            Err(error) => {
                failures.push(format!("{p}: resolver configuration read failed: {error}"))
            }
        }
    }
    let mut index = BTreeMap::<String, BTreeSet<String>>::new();
    for p in files
        .iter()
        .filter(|p| p.ends_with(".swift") && p.rsplit('/').next() != Some("Package.swift"))
    {
        let mut names = BTreeSet::new();
        for (name, path) in &declared {
            if p == path || p.starts_with(&format!("{path}/")) {
                names.insert(name.as_str());
            }
        }
        let dirs: Vec<_> = dir_of(p).split('/').filter(|d| !d.is_empty()).collect();
        let source_roots = ["source", "sources", "test", "tests"];
        let containers = [
            "framework",
            "frameworks",
            "library",
            "libraries",
            "module",
            "modules",
        ];
        for pair in dirs.windows(2) {
            let lower = pair[0].to_ascii_lowercase();
            if source_roots.contains(&lower.as_str()) || containers.contains(&lower.as_str()) {
                names.insert(pair[1]);
            }
        }
        if let Some(first) = dirs.first() {
            if !source_roots.contains(&first.to_ascii_lowercase().as_str()) {
                names.insert(first);
            }
        }
        for name in names.into_iter().filter(|name| module_name(name)) {
            index.entry(name.to_owned()).or_default().insert(p.clone());
        }
    }
    index
        .into_iter()
        .map(|(name, paths)| (name, paths.into_iter().collect()))
        .collect()
}

pub(crate) fn resolve(
    source: &str,
    importer: &str,
    index: &BTreeMap<String, Vec<String>>,
) -> Vec<String> {
    let name = source.trim().split('.').next().unwrap_or("");
    if !module_name(name) {
        return vec![];
    }
    index
        .get(name)
        .into_iter()
        .flatten()
        .filter(|p| p.as_str() != importer)
        .cloned()
        .collect()
}
