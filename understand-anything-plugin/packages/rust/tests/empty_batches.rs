use serde_json::json;
use std::{fs, process::Command};

#[test]
fn empty_loaded_batch_is_reported_even_beside_valid_results() {
    let tmp = tempfile::tempdir().unwrap();
    let inter = tmp.path().join(".ua/intermediate");
    fs::create_dir_all(&inter).unwrap();
    fs::write(inter.join("batch-0.json"), r#"{"nodes":[],"edges":[]}"#).unwrap();
    fs::write(inter.join("batch-1.json"), json!({"nodes":[{"id":"file:a.rs","type":"file","name":"a.rs","filePath":"a.rs","tags":[]}],"edges":[]}).to_string()).unwrap();
    let run = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("merge_batch_graphs")
        .arg(tmp.path())
        .output()
        .unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    let diagnostic = "batch-0.json loaded but contributed 0 nodes and 0 edges";
    assert!(String::from_utf8_lossy(&run.stderr).contains(diagnostic));
    assert!(
        fs::read_to_string(inter.join("batch-merge-report.txt"))
            .unwrap()
            .contains(diagnostic)
    );
    let graph: serde_json::Value =
        serde_json::from_slice(&fs::read(inter.join("assembled-graph.json")).unwrap()).unwrap();
    assert_eq!(graph["nodes"].as_array().unwrap().len(), 1);
}
