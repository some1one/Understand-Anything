//! Command boundaries for migrated skill helpers and their compatibility APIs.
use serde_json::{Value, json};
use std::{collections::BTreeSet, fs, io, path::Path};
use understand_anything::{self as ua, Error, Result};

pub const COMMANDS: &[&str] = &[
    "capture_project_context",
    "write_changed_files",
    "prune_incremental_batch",
    "save_knowledge_graph",
    "diff_context",
    "query_graph",
    "query_payload",
    "query_terms",
    "helper_request",
    "refresh_query_dictionaries",
];
fn field<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value[key]
        .as_str()
        .ok_or_else(|| Error::Invalid(format!("{key} must be a string")))
}
fn words(value: &Value) -> BTreeSet<String> {
    ua::strings(value).into_iter().collect()
}
fn request(command: &str) -> Result<Value> {
    let value: Value = serde_json::from_reader(io::stdin().lock())?;
    match command {
        "query_payload" => ua::query_graph::build_payload(
            &value["graph"],
            field(&value, "query")?,
            &words(&value["cachedWords"]),
        ),
        "query_terms" => Ok(json!(ua::query_terms::Lexicon::load()?.query_terms(
            field(&value, "query")?,
            &words(&value["graphWords"]),
            &words(&value["cachedWords"])
        ))),
        _ => match field(&value, "operation")? {
            "graph_vocabulary" => Ok(json!(ua::query_terms::graph_vocabulary(&value["graph"]))),
            "cached_words" => Ok(json!(ua::query_dictionary::cached_words(
                Path::new(field(&value, "path")?),
                field(&value, "raw")?.as_bytes()
            ))),
            "shallow_tree" => Ok(json!(ua::context_helpers::shallow_tree(Path::new(field(
                &value, "root"
            )?)))),
            "default_base" => Ok(json!(ua::context_helpers::default_base(Path::new(field(
                &value, "root"
            )?)))),
            "diff_files" => Ok(json!(ua::context_helpers::diff_files(
                Path::new(field(&value, "root")?),
                value["base"].as_str()
            )?)),
            operation => Err(Error::Invalid(format!(
                "Unknown helper operation: {operation}"
            ))),
        },
    }
}
pub fn run(command: &str, args: &[String]) -> Result<i32> {
    let payload = if ["query_payload", "query_terms", "helper_request"].contains(&command) {
        if !args.is_empty() {
            return Err(Error::Invalid(format!("{command} accepts JSON on stdin")));
        }
        request(command)?
    } else {
        let valid = match command {
            "query_graph" => args.len() >= 2,
            "write_changed_files" | "prune_incremental_batch" => args.len() == 2,
            "diff_context" => (1..=2).contains(&args.len()),
            _ => args.len() == 1,
        };
        if !valid {
            return Err(Error::Invalid(format!(
                "Usage: understand-anything-rs {command} <project-root> [command arguments]"
            )));
        }
        let root = std::env::current_dir()?.join(&args[0]);
        match command {
            "capture_project_context" => ua::context_helpers::capture_project_context(&root)?,
            "write_changed_files" => {
                let path = ua::context_helpers::write_changed_files(&root, &args[1])?;
                println!("{}", path.as_str().unwrap());
                return Ok(0);
            }
            "prune_incremental_batch" => {
                ua::context_helpers::prune_incremental_batch(&root, Path::new(&args[1]))?
            }
            "save_knowledge_graph" => {
                let summary = ua::context_helpers::save_knowledge_graph(&root)?;
                ua::query_dictionary::refresh(
                    &root.join(".understand-anything/knowledge-graph.json"),
                )?;
                summary
            }
            "diff_context" => {
                ua::context_helpers::diff_context(&root, args.get(1).map(String::as_str))?
            }
            "refresh_query_dictionaries" => ua::query_dictionary::refresh(
                &root.join(".understand-anything/knowledge-graph.json"),
            )?,
            "query_graph" => {
                let path = root.join(".understand-anything/knowledge-graph.json");
                let raw = fs::read(&path)?;
                ua::query_graph::build_payload(
                    &serde_json::from_slice(&raw)?,
                    args[1..].join(" ").trim(),
                    &ua::query_dictionary::cached_words(&path, &raw),
                )?
            }
            _ => unreachable!(),
        }
    };
    print!("{}", ua::query_graph::serialize(&payload)?);
    Ok(0)
}
