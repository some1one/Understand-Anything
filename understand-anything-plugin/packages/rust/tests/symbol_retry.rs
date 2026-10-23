use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
use understand_anything::{persistence::{read_json, write_json}, updates};
fn git(root: &Path, args: &[&str]) -> String {
    let output = Command::new("git").args(args).current_dir(root).output().unwrap();
    assert!(output.status.success()); String::from_utf8(output.stdout).unwrap().trim().into()
}
fn node(path: &str) -> Value { json!({"id":format!("file:{path}"),"type":"file","filePath":path,"summary":"fresh"}) }
#[test]
fn retry_is_scoped_single_use_and_preserves_successful_files_and_inbound_edges() {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    git(root, &["init", "-q"]); git(root, &["config", "user.name", "Fixture"]); git(root, &["config", "user.email", "fixture@example.test"]);
    for path in ["a.rb", "b.rb"] { fs::write(root.join(path), "puts 1\n").unwrap(); }
    git(root, &["add", "."]); git(root, &["commit", "-qm", "fixture"]);
    let head = git(root, &["rev-parse", "HEAD"]);
    let inter = root.join(".ua/intermediate"); fs::create_dir_all(&inter).unwrap();
    let graph = json!({"nodes":[node("a.rb"),node("b.rb")],"edges":[{"source":"file:b.rb","target":"file:a.rb","type":"depends_on","description":"fresh incoming"}]});
    let save = |name: &str, value: &Value| write_json(&inter.join(name), value).unwrap();
    write_json(&root.join(".ua/knowledge-graph.json"), &json!({"nodes":[],"edges":[]})).unwrap();
    save("auto-update-state.json", &json!({"previousCommit":head,"currentCommit":head}));
    save("change-analysis.json", &json!({"filesToReanalyze":["a.rb","b.rb"]}));
    save("merged-graph.json", &graph);
    save("scan-result.json", &json!({"files":[{"path":"a.rb","fileCategory":"code","language":"ruby","sizeLines":1},{"path":"b.rb","fileCategory":"code","language":"ruby","sizeLines":1}],"importMap":{"a.rb":[],"b.rb":[]}}));
    save("batch-0.json", &graph);
    let candidates = json!({"version":1,"baseCommit":head,"headCommit":head,"nodes":graph["nodes"],"edges":[{"source":"file:b.rb","target":"function:a.rb:missing","type":"calls"}],"graphHash":understand_anything::incremental_symbols::edge_candidate_hash(&graph).unwrap()});
    save("incremental-edge-candidates.json", &candidates);
    save("incremental-symbol-report.json", &json!({"version":1,"ok":false,"baseCommit":head,"headCommit":head,"unresolvedFiles":["a.rb"],"errors":[],"graphHash":understand_anything::fingerprints::content_hash(&serde_json::to_string(&graph).unwrap())}));
    let result = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args(["auto_update_prepare_symbol_retry",root.to_str().unwrap()]).output().unwrap();
    assert!(result.status.success(), "{}", String::from_utf8_lossy(&result.stderr));
    assert_eq!(read_json(&inter.join("incremental-symbol-retry.json")).unwrap()["edgeCandidates"], candidates);
    let summary = read_json(&inter.join("dispatch-summary.json")).unwrap();
    assert_eq!(summary["filesToReanalyze"], json!(["a.rb"]));
    assert!(!inter.join("batch-0.json").exists());
    let archive = fs::read_dir(&inter).unwrap().filter_map(Result::ok).find(|e| e.file_name().to_string_lossy().starts_with("symbol-retry-originals-")).unwrap();
    assert_eq!(read_json(&archive.path().join("batch-0.json")).unwrap(), graph);
    assert!(updates::prepare_symbol_retry(root).unwrap_err().to_string().contains("already been used"));
    save("batch-0.json", &json!({"nodes":[node("a.rb")],"edges":[]}));
    let merged = updates::apply_batches(root).unwrap();
    assert!(merged["nodes"].as_array().unwrap().iter().any(|n| n["id"]=="file:b.rb" && n["summary"]=="fresh"));
    assert_eq!(merged["edges"], graph["edges"]);
    let mut retry = read_json(&inter.join("incremental-symbol-retry.json")).unwrap();
    retry["status"] = json!("preparing"); save("incremental-symbol-retry.json", &retry);
    assert!(updates::apply_batches(root).unwrap_err().to_string().contains("incomplete"));
    assert!(updates::prepare_symbol_retry(root).is_err());
    fs::write(inter.join("incremental-symbol-retry.json"), "{broken").unwrap();
    assert!(updates::apply_batches(root).is_err());
    assert!(updates::prepare_symbol_retry(root).is_err());
}

#[test]
fn candidate_evidence_rejects_a_different_graph_or_revision() {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    let inter = root.join(".ua/intermediate"); fs::create_dir_all(&inter).unwrap();
    let graph = json!({"nodes":[],"edges":[]});
    let state = json!({"previousCommit":"base","currentCommit":"head"});
    let record = json!({"version":1,"baseCommit":"base","headCommit":"head","nodes":[],"edges":[],"graphHash":understand_anything::incremental_symbols::edge_candidate_hash(&graph).unwrap()});
    write_json(&inter.join("incremental-edge-candidates.json"), &record).unwrap();
    let read = understand_anything::incremental_symbols::read_edge_candidates;
    assert!(read(root, &state, &graph).is_ok());
    assert!(read(root, &state, &json!({"nodes":[],"edges":[],"layers":[{"id":"layer:core"}]})).is_ok());
    assert!(read(root, &state, &json!({"nodes":[node("changed.rb")],"edges":[]})).is_err());
    assert!(read(root, &json!({"previousCommit":"base","currentCommit":"other"}), &graph).is_err());
}
