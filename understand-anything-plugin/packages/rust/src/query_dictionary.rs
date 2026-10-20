//! Build offline, project-scoped CSpell caches when a graph is published.
//! Search never needs to load the full source dictionaries.
use crate::{Result, array, strings};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};

pub fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let temp = path.with_extension(format!(
        "{}-{}.tmp",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| crate::Error::Invalid(error.to_string()))?
            .as_nanos()
    ));
    fs::write(&temp, bytes)?;
    fs::rename(temp, path)?;
    Ok(())
}

pub fn graph_vocabulary(graph: &Value) -> BTreeSet<String> {
    crate::query_terms::graph_vocabulary(graph)
}

fn dictionary_for(language: &str) -> Option<&'static str> {
    match language.to_lowercase().as_str() {
        "c" | "c++" | "cpp" | "objective-c" | "objective-cpp" => Some("cpp"),
        "c#" | "csharp" => Some("csharp"),
        "javascript" | "typescript" | "js" | "ts" | "jsx" | "tsx" | "vue" | "svelte" => {
            Some("typescript")
        }
        "go" | "golang" => Some("golang"),
        "bash" | "sh" | "zsh" | "shell" | "shellscript" => Some("shell"),
        "docker" | "dockerfile" => Some("docker"),
        "hcl" | "terraform" => Some("terraform"),
        "scss" | "sass" | "less" | "css" => Some("css"),
        "html" => Some("html"),
        "java" => Some("java"),
        "kotlin" => Some("kotlin"),
        "lua" => Some("lua"),
        "php" => Some("php"),
        "powershell" => Some("powershell"),
        "python" => Some("python"),
        "ruby" => Some("ruby"),
        "rust" => Some("rust"),
        "scala" => Some("scala"),
        "sql" => Some("sql"),
        "swift" => Some("swift"),
        "dart" => Some("dart"),
        _ => None,
    }
}

pub fn refresh(graph_path: &Path) -> Result<Value> {
    let raw = fs::read(graph_path)?;
    let graph: Value = serde_json::from_slice(&raw)?;
    let sources = crate::dictionary_data::Sources::open()?;
    let lexicon = crate::query_terms::Lexicon::load()?;
    let mut languages: BTreeSet<String> = strings(&graph["project"]["languages"])
        .into_iter()
        .map(|s| s.to_lowercase())
        .collect();
    for node in array(&graph, "nodes") {
        if let Some(path) = node["filePath"].as_str() {
            let language = crate::scan::detect_language(path);
            if language != "unknown" {
                languages.insert(language);
            }
        }
    }
    languages.remove("");
    languages.remove("unknown");
    let mut selected: BTreeSet<String> = languages
        .iter()
        .filter_map(|l| dictionary_for(l).map(str::to_owned))
        .collect();
    // Shared software vocabulary applies to every development language.
    selected.insert("software-terms".into());
    if selected.contains("typescript") {
        selected.insert("node".into());
    }
    let dictionaries = sources.technical(&selected)?;
    let vocabulary = graph_vocabulary(&graph);
    let dir = graph_path.parent().unwrap().join("query-dictionaries");
    fs::create_dir_all(&dir)?;
    let mut files = BTreeMap::new();
    for name in selected {
        let Some(words) = dictionaries.get(&name) else {
            continue;
        };
        let remaining: Vec<_> = words
            .iter()
            .filter(|word| !vocabulary.contains(&crate::query_terms::normalized(word)))
            .filter(|word| lexicon.needs_technical_protection(word))
            .collect();
        let bytes = serde_json::to_vec(&remaining)?;
        let digest = hash(&bytes);
        // Immutable files let in-flight readers finish against the old manifest.
        let filename = format!("{name}-{digest}.json");
        let path = dir.join(&filename);
        if !fs::read(&path).is_ok_and(|existing| hash(&existing) == digest) {
            atomic_write(&path, &bytes)?;
        }
        files.insert(
            name,
            json!({"file":filename,"sha256":digest,"words":remaining.len()}),
        );
    }
    let manifest = json!({"version":3,"graphSha256":hash(&raw),
        "lemmaSha256":hash(&serde_json::to_vec(&sources.lemmas()?)?),
        "languages":languages,"dictionaries":files});
    atomic_write(
        &dir.join("manifest.json"),
        &serde_json::to_vec_pretty(&manifest)?,
    )?;
    Ok(manifest)
}

/// Query-time reads only active cache files, never the full CSpell dictionary.
pub fn cached_words(graph_path: &Path, raw: &[u8]) -> BTreeSet<String> {
    match read_cache(graph_path, raw) {
        Ok(words) => words,
        Err(error) => {
            eprintln!(
                "Technical dictionary cache unavailable ({error}); using graph names only. Run /understand or refresh_query_dictionaries to refresh it."
            );
            BTreeSet::new()
        }
    }
}
fn read_cache(graph_path: &Path, raw: &[u8]) -> Result<BTreeSet<String>> {
    let dir = graph_path.parent().unwrap().join("query-dictionaries");
    let manifest: Value = serde_json::from_slice(&fs::read(dir.join("manifest.json"))?)?;
    if manifest["version"] != 3 || manifest["graphSha256"] != hash(raw) {
        return Err(crate::Error::Invalid(
            "cache does not match the saved graph or tokenizer version".into(),
        ));
    }
    let lemmas = crate::dictionary_data::Sources::open()?.lemmas()?;
    if manifest["lemmaSha256"] != hash(&serde_json::to_vec(&lemmas)?) {
        return Err(crate::Error::Invalid(
            "lemma dictionary changed; refresh technical caches".into(),
        ));
    }
    let entries = manifest["dictionaries"]
        .as_object()
        .ok_or_else(|| crate::Error::Invalid("invalid dictionary cache manifest".into()))?;
    let pattern = regex::Regex::new(r"^[a-z][a-z-]*-[0-9a-f]{64}\.json$").unwrap();
    let mut words = BTreeSet::new();
    for entry in entries.values() {
        let filename = entry["file"].as_str().unwrap_or("");
        if !pattern.is_match(filename) {
            return Err(crate::Error::Invalid(
                "invalid dictionary cache filename".into(),
            ));
        }
        let bytes = fs::read(dir.join(filename))?;
        if entry["sha256"] != hash(&bytes) {
            return Err(crate::Error::Invalid(
                "dictionary cache checksum mismatch".into(),
            ));
        }
        let entries: Vec<String> = serde_json::from_slice(&bytes)?;
        words.extend(entries);
    }
    Ok(words)
}
