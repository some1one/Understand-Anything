//! Version-locked parser management. Only the baseline's thirteen grammars are supported.
use crate::{Error, Result};
use std::path::Path;
pub const VERSION: &str = "1.20.0";
pub const LANGUAGES: &[&str] = &[
    "typescript",
    "tsx",
    "javascript",
    "python",
    "go",
    "rust",
    "java",
    "kotlin",
    "csharp",
    "php",
    "ruby",
    "c",
    "cpp",
];
pub fn configure(cache_dir: Option<&Path>) -> Result<()> {
    if let Some(dir) = cache_dir {
        let config = tree_sitter_language_pack::PackConfig {
            cache_dir: Some(dir.to_path_buf()),
            ..Default::default()
        };
        tree_sitter_language_pack::configure(&config).map_err(|e| Error::Invalid(e.to_string()))?;
    }
    Ok(())
}
pub fn fetch(languages: &[String]) -> Result<()> {
    let names: Vec<&str> = if languages.is_empty() {
        LANGUAGES.to_vec()
    } else {
        languages.iter().map(String::as_str).collect()
    };
    for name in names {
        if !LANGUAGES.contains(&name) {
            return Err(Error::Invalid(format!("Unsupported grammar: {name}")));
        }
        eprintln!("Fetching parser {name} (language-pack {VERSION})");
        tree_sitter_language_pack::get_parser(name).map_err(|e| Error::Invalid(e.to_string()))?;
    }
    Ok(())
}
pub fn parse(language: &str, source: &str) -> Result<tree_sitter_language_pack::Tree> {
    if !LANGUAGES.contains(&language) {
        return Err(Error::Invalid(format!("Unsupported grammar: {language}")));
    }
    let mut parser = tree_sitter_language_pack::get_parser(language)
        .map_err(|e| Error::Invalid(e.to_string()))?;
    parser
        .parse(source)
        .ok_or_else(|| Error::Invalid(format!("Parser returned no tree: {language}")))
}
pub fn detect_registry_language(path: &str) -> Option<String> {
    let p = path.replace('\\', "/");
    let base = p.rsplit('/').next().unwrap_or(&p).to_lowercase();
    let table = &crate::tables()["registry"];
    if let Some(id) = table["_FILENAME_TO_ID"][&base].as_str() {
        return Some(id.into());
    }
    path.rfind('.')
        .and_then(|i| table["_EXT_TO_ID"][path[i..].to_lowercase()].as_str())
        .map(str::to_owned)
}
