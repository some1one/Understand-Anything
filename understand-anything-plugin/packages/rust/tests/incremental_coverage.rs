use serde_json::json;
use std::fs;
use understand_anything::{persistence::{read_json, write_json}, updates::{apply_batches, finalize, validate_analyzed_file_coverage}};

#[test]
fn coverage_accepts_whole_files_and_data_children_but_not_symbols_or_stubs() {
    for (kind, id, valid) in [
        ("config", "config:a", true), ("schema", "schema:a", true),
        ("table", "table:a:users", true), ("endpoint", "endpoint:a:get", true),
        ("function", "function:a:f", false), ("table", "table:a:", false),
        ("service", "service:a:child", false),
    ] {
        let nodes = vec![json!({"id":id,"type":kind,"filePath":"a"})];
        assert_eq!(validate_analyzed_file_coverage(&nodes, &["a".into()]).is_ok(), valid, "{id}");
    }
    assert!(validate_analyzed_file_coverage(&[json!({"id":"file:a","type":"file","filePath":"a","stub":true})], &["a".into()]).is_err());
}
#[test]
fn absent_or_corrupt_batches_cannot_publish_a_graph_missing_changed_files() {
    let temp = tempfile::tempdir().unwrap();
    let data = temp.path().join(".ua");
    let inter = data.join("intermediate");
    fs::create_dir_all(&inter).unwrap();
    let saved = json!({"nodes":[{"id":"file:a","type":"file","filePath":"a"}],"edges":[]});
    write_json(&data.join("knowledge-graph.json"), &saved).unwrap();
    write_json(&inter.join("change-analysis.json"), &json!({"filesToReanalyze":["a"]})).unwrap();
    write_json(&inter.join("merged-graph.json"), &json!({"nodes":[],"edges":[]})).unwrap();
    for content in [None, Some("{invalid"), Some("{}"), Some(r#"{"nodes":[],"edges":[]}"#)] {
        if let Some(content) = content { fs::write(inter.join("batch-0.json"), content).unwrap(); }
        assert!(apply_batches(temp.path()).is_err());
        assert_eq!(read_json(&data.join("knowledge-graph.json")).unwrap(), saved);
        assert!(finalize(temp.path()).is_err());
        assert_eq!(read_json(&data.join("knowledge-graph.json")).unwrap(), saved);
        assert!(!data.join("meta.json").exists());
    }
}
