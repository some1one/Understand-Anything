//! Native analysis APIs. JSON boundary values retain extension metadata.
pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Json(#[from] serde_json::Error),
    #[error("{0}")]
    Invalid(String),
    #[error("{message}")]
    Usage { status: u8, message: String },
    #[error("{path}: {message}")]
    Validation { path: String, message: String },
    #[error("{0}")]
    Http(#[from] reqwest::Error),
}
pub mod partition;
pub mod persistence;
pub mod search;
pub mod validation;
pub fn array<'a>(v: &'a serde_json::Value, key: &str) -> &'a [serde_json::Value] {
    v.get(key)
        .and_then(serde_json::Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}
pub fn strings(v: &serde_json::Value) -> Vec<String> {
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(str::to_owned))
                .collect()
        })
        .unwrap_or_default()
}
pub fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)
}
pub mod scan;
pub mod schemas;
pub fn tables() -> &'static serde_json::Value {
    static TABLES: std::sync::OnceLock<serde_json::Value> = std::sync::OnceLock::new();
    TABLES.get_or_init(|| {
        serde_json::from_str(include_str!("../reference/tables.json")).expect("embedded tables")
    })
}
pub mod analytics;
pub mod assembly;
pub mod batch_merge;
pub mod batch_validation;
pub mod batching;
pub mod domain_context;
pub mod embeddings;
pub mod file_graph;
pub mod fingerprints;
pub mod ignore_generator;
pub mod imports;
pub mod input;
pub mod merge;
pub mod noncode;
pub mod parsers;
pub mod seed;
pub mod skills;
pub mod staleness;
pub mod strict_validation;
pub mod structure;
pub mod updates;

pub mod models;

pub mod batch_files;
pub mod context_helpers;
pub mod dictionary_data;
pub mod query_dictionary;
pub mod query_graph;
pub mod query_terms;

pub mod symbol_scopes;

mod symbol_coverage;

mod symbol_effects;

pub mod incremental_symbols;

mod receivers;

mod swift_imports;
mod scala_imports;
pub mod freshness;

pub mod file_lists;

mod symbol_bindings;
