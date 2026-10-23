use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
use understand_anything::{incremental_symbols::capture_baseline, persistence::{read_json, write_json}, updates};
fn git(root: &Path, args: &[&str]) -> String {
    let out = Command::new("git").args(args).current_dir(root).output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}
fn file(path: &str) -> Value { json!({"id":format!("file:{path}"),"type":"file","filePath":path,"name":path}) }
fn symbol(id: &str) -> Value { json!({"id":id,"type":"function","filePath":"file.ts","name":"run"}) }
#[test]
#[ignore = "requires pinned TypeScript grammar; run with UA_TEST_PARSER_CACHE"]
fn finalization_blocks_symbol_loss_and_recovers_inbound_edges_after_verified_id_change() {
    let cache = std::env::var("UA_TEST_PARSER_CACHE").expect("set UA_TEST_PARSER_CACHE");
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    git(root, &["init", "-q"]); git(root, &["config", "user.email", "fixture@example.test"]); git(root, &["config", "user.name", "Fixture"]);
    fs::write(root.join("file.ts"), "function run() {} function keep() {}\n").unwrap();
    git(root, &["add", "."]); git(root, &["commit", "-qm", "base"]);
    let base = git(root, &["rev-parse", "HEAD"]);
    fs::write(root.join("file.ts"), "function run() { return 1; } function keep() {}\n").unwrap();
    git(root, &["add", "."]); git(root, &["commit", "-qm", "head"]);
    let head = git(root, &["rev-parse", "HEAD"]);
    let data = root.join(".ua"); let inter = data.join("intermediate"); fs::create_dir_all(&inter).unwrap();
    let previous = json!({"nodes":[file("file.ts"),file("caller.ts"),symbol("function:file.ts:run")],
        "edges":[{"source":"file:caller.ts","target":"function:file.ts:run","type":"calls","description":"preserve this"},
            {"source":"file:caller.ts","target":"file:file.ts","type":"imports"}],"layers":[]});
    write_json(&data.join("knowledge-graph.json"), &previous).unwrap();
    updates::write_meta(root, &base, None).unwrap();
    let state = json!({"previousCommit":base,"currentCommit":head});
    let analysis = json!({"filesToReanalyze":["file.ts"],"deletedFiles":[]});
    write_json(&inter.join("auto-update-state.json"), &state).unwrap();
    write_json(&inter.join("change-analysis.json"), &analysis).unwrap();
    capture_baseline(root, &state, &analysis, &previous).unwrap();
    let incomplete = json!({"nodes":[file("file.ts"),file("caller.ts")],"edges":[],"layers":[]});
    write_json(&inter.join("merged-graph.json"), &incomplete).unwrap();
    let dictionary = data.join("dictionary-config.json"); fs::write(&dictionary, "{\"version\":1}").unwrap();
    let run = || Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args(["--parser-cache-dir", &cache, "auto_update_finalize", root.to_str().unwrap()])
        .env("UA_DICTIONARY_CONFIG", &dictionary)
        .env("UA_DICTIONARY_DIR", concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/dictionaries"))
        .output().unwrap();
    let meta = fs::read(data.join("meta.json")).unwrap();
    let failed = run(); assert!(!failed.status.success(), "{}", String::from_utf8_lossy(&failed.stdout));
    assert_eq!(read_json(&data.join("knowledge-graph.json")).unwrap(), previous);
    assert_eq!(fs::read(data.join("meta.json")).unwrap(), meta);
    assert!(!data.join("fingerprints.json").exists());
    let report = read_json(&inter.join("incremental-symbol-report.json")).unwrap();
    assert_eq!(report["ok"], false, "{report}");
    assert_eq!(report["files"][0]["missing"][0]["status"], "still-present");
    let repaired = json!({"nodes":[file("file.ts"),file("caller.ts"),symbol("func:file.ts:run")],"edges":[],"layers":[]});
    write_json(&inter.join("merged-graph.json"), &repaired).unwrap();
    write_json(&inter.join("scan-result.json"), &json!({"files":[{"language":"typescript"},{"language":"python"},{"language":"typescript"}],"importMapRefreshPaths":["caller.ts"],"importMap":{"caller.ts":[]}})).unwrap();
    // Repeated preparation must retain the original comparison baseline if
    // an interrupted finalization has already persisted a replacement graph.
    capture_baseline(root, &state, &analysis, &repaired).unwrap();
    assert_eq!(read_json(&inter.join("incremental-symbol-baseline.json")).unwrap()["graph"], previous);
    let mut first_attempt = repaired.clone();
    let keep = json!({"id":"function:file.ts:keep","type":"function","filePath":"file.ts","name":"keep"});
    first_attempt["nodes"].as_array_mut().unwrap().push(keep.clone());
    write_json(&inter.join("incremental-symbol-retry.json"), &json!({"version":1,"status":"ready","baseCommit":base,"headCommit":head,"files":["file.ts"],"graph":first_attempt,"edgeCandidates":{"nodes":[file("caller.ts")],"edges":[{"source":"file:caller.ts","target":"function:file.ts:run","type":"references","description":"fresh analyzer evidence","weight":3,"direction":"forward"}]}})).unwrap();
    let lost_fresh_symbol = run();
    assert!(!lost_fresh_symbol.status.success());
    let report = read_json(&inter.join("incremental-symbol-report.json")).unwrap();
    assert!(report["files"].as_array().unwrap().iter().any(|file| file["phase"] == "repair" && file["missing"].as_array().unwrap().iter().any(|node| node["name"] == "keep" && node["status"] == "still-present")), "{report}");
    let mut repaired = repaired;
    repaired["nodes"].as_array_mut().unwrap().push(keep);
    write_json(&inter.join("merged-graph.json"), &repaired).unwrap();
    let success = run(); assert!(success.status.success(), "{}", String::from_utf8_lossy(&success.stderr));
    let saved = read_json(&data.join("knowledge-graph.json")).unwrap();
    assert!(saved["edges"].as_array().unwrap().iter().any(|e| e["source"]=="file:caller.ts" && e["target"]=="func:file.ts:run" && e["description"]=="preserve this"));
    assert!(saved["edges"].as_array().unwrap().iter().any(|e| e["target"] == "func:file.ts:run" && e["description"] == "fresh analyzer evidence"));
    assert!(!saved["edges"].as_array().unwrap().iter().any(|edge| edge["type"] == "imports"));
    assert_eq!(saved["project"]["gitCommitHash"], head);
    assert_eq!(saved["project"]["languages"], json!(["python","typescript"]));
    assert!(saved["project"]["analyzedAt"].as_str().unwrap().contains('T'));
    assert_eq!(read_json(&data.join("meta.json")).unwrap()["gitCommitHash"], head);
}

#[test]
fn missing_or_mismatched_baseline_cannot_authorize_publication() {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    let data = root.join(".ua"); let inter = data.join("intermediate");
    fs::create_dir_all(&inter).unwrap();
    let graph = json!({"nodes":[file("file.ts"),symbol("function:file.ts:run")],"edges":[]});
    write_json(&data.join("knowledge-graph.json"), &graph).unwrap();
    let state = json!({"previousCommit":"a".repeat(40),"currentCommit":"b".repeat(40)});
    let analysis = json!({"filesToReanalyze":["file.ts"]});
    let mut candidate = graph.clone();
    assert!(understand_anything::incremental_symbols::validate_prepared(root, &state, &analysis, &mut candidate).is_err());
    capture_baseline(root, &state, &analysis, &graph).unwrap();
    let mut changed = state.clone(); changed["currentCommit"] = json!("c".repeat(40));
    let error = understand_anything::incremental_symbols::validate_prepared(root, &changed, &analysis, &mut candidate).unwrap_err();
    assert!(error.to_string().contains("does not match"));
    assert_eq!(candidate, graph);
    assert_eq!(read_json(&data.join("knowledge-graph.json")).unwrap(), graph);
}
