mod common;
use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
use understand_anything as ua;

fn cached(dir: &Path, manifest: &Value, language: &str) -> Vec<String> {
    let path = dir
        .join("query-dictionaries")
        .join(manifest["dictionaries"][language]["file"].as_str().unwrap());
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}

#[test]
fn publishing_scopes_prunes_and_restores_language_words() {
    if common::with_dictionaries("publishing_scopes_prunes_and_restores_language_words") {
        return;
    }
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let dir = ua::persistence::data_dir(root);
    let graph = json!({"project":{"languages":["Rust"]},"nodes":[]});
    ua::persistence::save_graph(root, &graph).unwrap();
    let manifest_path = dir.join("query-dictionaries/manifest.json");
    let manifest = ua::persistence::read_json(&manifest_path).unwrap();
    assert_eq!(manifest["dictionaries"].as_object().unwrap().len(), 2);
    assert!(cached(&dir, &manifest, "rust").contains(&"unsafe".into()));
    let mut changed = graph.clone();
    changed["nodes"] = json!([{"id":"ref", "name":"unsafe"}]);
    ua::persistence::save_graph(root, &changed).unwrap();
    let pruned = ua::persistence::read_json(&manifest_path).unwrap();
    assert!(!cached(&dir, &pruned, "rust").contains(&"unsafe".into()));
    // The previous generation remains readable by an in-flight query.
    assert!(cached(&dir, &manifest, "rust").contains(&"unsafe".into()));
    ua::persistence::save_graph(root, &graph).unwrap();
    let restored = ua::persistence::read_json(&manifest_path).unwrap();
    assert!(cached(&dir, &restored, "rust").contains(&"unsafe".into()));
    // Refresh repairs a corrupted immutable file instead of trusting its name.
    let damaged = dir
        .join("query-dictionaries")
        .join(restored["dictionaries"]["rust"]["file"].as_str().unwrap());
    fs::write(damaged, "broken").unwrap();
    ua::query_dictionary::refresh(&dir.join("knowledge-graph.json")).unwrap();
    assert!(cached(&dir, &restored, "rust").contains(&"unsafe".into()));
    ua::persistence::save_graph(
        root,
        &json!({"project":{"languages":["Python"]},"nodes":[]}),
    )
    .unwrap();
    let switched = ua::persistence::read_json(&manifest_path).unwrap();
    assert!(switched["dictionaries"].get("python").is_some());
    assert!(switched["dictionaries"].get("rust").is_none());
}

#[test]
fn unknown_languages_use_only_shared_terms_and_file_detection_scopes_languages() {
    if common::with_dictionaries(
        "unknown_languages_use_only_shared_terms_and_file_detection_scopes_languages",
    ) {
        return;
    }
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let manifest = ua::persistence::data_dir(root).join("query-dictionaries/manifest.json");
    ua::persistence::save_graph(root, &json!({"nodes":[]})).unwrap();
    let initial = ua::persistence::read_json(&manifest).unwrap();
    assert_eq!(initial["dictionaries"].as_object().unwrap().len(), 1);
    assert!(initial["dictionaries"].get("software-terms").is_some());
    ua::persistence::save_graph(root, &json!({"nodes":[{"filePath":"src/main.rs"}]})).unwrap();
    let detected = ua::persistence::read_json(&manifest).unwrap();
    assert_eq!(detected["dictionaries"].as_object().unwrap().len(), 2);
    assert!(detected["dictionaries"].get("rust").is_some());
    ua::persistence::save_graph(
        root,
        &json!({"project":{"languages":["unknown"]},"nodes":[]}),
    )
    .unwrap();
    let unidentified = ua::persistence::read_json(&manifest).unwrap();
    assert_eq!(unidentified["dictionaries"].as_object().unwrap().len(), 1);
    assert!(unidentified["dictionaries"].get("software-terms").is_some());
    ua::persistence::save_graph(
        root,
        &json!({"project":{"languages":["Elixir"]},"nodes":[]}),
    )
    .unwrap();
    let unsupported = ua::persistence::read_json(&manifest).unwrap();
    assert_eq!(unsupported["dictionaries"].as_object().unwrap().len(), 1);
    assert!(unsupported["dictionaries"].get("software-terms").is_some());
}

#[test]
fn native_save_and_python_search_use_project_cache() {
    if common::with_dictionaries("native_save_and_python_search_use_project_cache") {
        return;
    }
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let dir = ua::persistence::data_dir(root);
    fs::create_dir_all(dir.join("intermediate")).unwrap();
    let mut nodes: Vec<Value> = (0..30)
        .map(|i| json!({"id":format!("post:{i}"),"name":"POST", "summary":"Handles requests"}))
        .collect();
    nodes.push(json!({"id":"get", "name":"GET", "summary":"Handles requests"}));
    let graph = json!({"project":{"languages":["Python"]},"nodes":nodes});
    ua::persistence::write_json(&dir.join("intermediate/assembled-graph.json"), &graph).unwrap();
    // Exercise the normal Python save entrypoint in a packaged layout, without
    // Cargo, Node, or source dictionary files in that layout.
    let plugin = root.join("plugin with spaces");
    let engine = plugin.join("packages/rust");
    let scripts = plugin.join("skills/understand/scripts");
    fs::create_dir_all(engine.join("bin")).unwrap();
    fs::create_dir_all(&scripts).unwrap();
    let source = Path::new(env!("CARGO_MANIFEST_DIR"));
    fs::copy(source.join("run.sh"), engine.join("run.sh")).unwrap();
    fs::copy(
        env!("CARGO_BIN_EXE_understand-anything-rs"),
        engine.join("bin/understand-anything-rs"),
    )
    .unwrap();
    fs::create_dir_all(plugin.join("scripts")).unwrap();
    fs::copy(
        source.join("../../scripts/native_engine.py"),
        plugin.join("scripts/native_engine.py"),
    )
    .unwrap();
    let saver = scripts.join("save_knowledge_graph.py");
    fs::copy(
        source.join("../../skills/understand/scripts/save_knowledge_graph.py"),
        &saver,
    )
    .unwrap();
    let out = Command::new("python3")
        .env(
            "UA_DICTIONARY_DIR",
            source.join("tests/fixtures/dictionaries"),
        )
        .arg("-S")
        .arg(saver)
        .arg(root)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let summary: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(summary["totalNodes"], 31);
    let script = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../skills/understand-chat/scripts/query_graph.py");
    let result = Command::new("python3")
        .env(
            "UA_ENGINE_BINARY",
            env!("CARGO_BIN_EXE_understand-anything-rs"),
        )
        .arg("-S")
        .arg(script)
        .arg(root)
        .arg("GET requests")
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert!(
        result.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let payload: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(payload["matchedNodes"].as_array().unwrap().len(), 1);
    assert_eq!(payload["matchedNodes"][0]["id"], "get");
}
