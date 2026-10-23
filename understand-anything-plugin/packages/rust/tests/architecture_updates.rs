use serde_json::{json, Value};
use std::{fs, process::Command};
use understand_anything::{
    architecture_updates::prepare,
    fingerprints,
    persistence::{read_json, write_json},
};

fn fixture(dir: &str) -> (tempfile::TempDir, Value) {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    fs::create_dir_all(root.join(dir).join("intermediate")).unwrap();
    fs::create_dir(root.join("docs")).unwrap();
    let paths: Vec<_> = (0..4).map(|i| format!("docs/{i}.md")).collect();
    for path in &paths {
        fs::write(root.join(path), "# Original\n").unwrap();
    }
    let graph = json!({"project":{"gitCommitHash":"base"},"nodes":paths.iter().map(|p| json!({"id":p,"type":"document","filePath":p})).collect::<Vec<_>>(),"edges":[],"layers":[{"id":"docs","name":"Documentation","nodeIds":paths}]});
    write_json(&root.join(dir).join("knowledge-graph.json"), &graph).unwrap();
    write_json(
        &root.join(dir).join("fingerprints.json"),
        &fingerprints::build_fingerprint_store(root, &paths, "base"),
    )
    .unwrap();
    write_json(
        &root.join(dir).join("intermediate/assembled-graph.json"),
        &graph,
    )
    .unwrap();
    write_json(
        &root.join(dir).join("intermediate/scan-result.json"),
        &json!({"files":paths.iter().map(|p|json!({"path":p})).collect::<Vec<_>>()}),
    )
    .unwrap();
    (temp, graph)
}
#[test]
fn local_updates_reuse_layers_in_both_data_directories_and_cli() {
    for dir in [".ua", ".understand-anything"] {
        let (temp, _) = fixture(dir);
        let root = temp.path();
        fs::write(root.join("docs/0.md"), "# Changed meaning\n").unwrap();
        let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .args(["prepare_architecture_update", root.to_str().unwrap()])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let plan: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(plan["action"], "PARTIAL_UPDATE");
        assert_eq!(plan["rerunArchitecture"], false);
        assert_eq!(plan["skipAssembleReviewer"], true);
        let layers = read_json(&root.join(dir).join("intermediate/layers.json")).unwrap();
        assert_eq!(layers[0]["name"], "Documentation");
        assert_eq!(layers[0]["nodeIds"].as_array().unwrap().len(), 4);
    }
}
#[test]
fn directory_changes_use_before_and_after_selected_inventories() {
    let (temp, mut graph) = fixture(".ua");
    let root = temp.path();
    fs::write(root.join("new.md"), "# New\n").unwrap();
    graph["nodes"]
        .as_array_mut()
        .unwrap()
        .push(json!({"id":"new.md","type":"document","filePath":"new.md"}));
    write_json(&root.join(".ua/intermediate/assembled-graph.json"), &graph).unwrap();
    let files: Vec<_> = graph["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .map(|n| json!({"path":n["filePath"]}))
        .collect();
    write_json(
        &root.join(".ua/intermediate/scan-result.json"),
        &json!({"files":files}),
    )
    .unwrap();
    let plan = prepare(root, false).unwrap();
    assert_eq!(plan["action"], "ARCHITECTURE_UPDATE");
    assert_eq!(plan["rerunArchitecture"], true);
    assert!(!root.join(".ua/intermediate/layers.json").exists());
}
#[test]
fn explicit_full_and_unusable_baselines_require_architecture() {
    let (temp, mut graph) = fixture(".ua");
    let root = temp.path();
    let plan = prepare(root, true).unwrap();
    assert_eq!(plan["rerunArchitecture"], true);
    assert_eq!(plan["skipAssembleReviewer"], false);
    graph["project"]["gitCommitHash"] = json!("different");
    write_json(&root.join(".ua/knowledge-graph.json"), &graph).unwrap();
    assert_eq!(prepare(root, false).unwrap()["rerunArchitecture"], true);
}
#[test]
fn failed_scan_or_unreadable_source_preserves_existing_layer_artifact() {
    let (temp, _) = fixture(".ua");
    let root = temp.path();
    let layers = root.join(".ua/intermediate/layers.json");
    write_json(&layers, &json!(["preserved"])).unwrap();
    fs::write(root.join("docs/0.md"), [0xff]).unwrap();
    assert!(prepare(root, false).is_err());
    assert_eq!(read_json(&layers).unwrap(), json!(["preserved"]));
    write_json(
        &root.join(".ua/intermediate/scan-result.json"),
        &json!({"files":[],"failures":["unreadable"]}),
    )
    .unwrap();
    assert!(prepare(root, true).is_err());
    assert_eq!(read_json(&layers).unwrap(), json!(["preserved"]));
}

#[test]
fn unselected_scan_files_do_not_trigger_architecture_but_major_changes_do() {
    let (temp, _) = fixture(".ua");
    let root = temp.path();
    let scan_path = root.join(".ua/intermediate/scan-result.json");
    let mut scan = read_json(&scan_path).unwrap();
    scan["files"]
        .as_array_mut()
        .unwrap()
        .push(json!({"path":"unselected/new.rs"}));
    write_json(&scan_path, &scan).unwrap();
    let unchanged = prepare(root, false).unwrap();
    assert_eq!(unchanged["action"], "SKIP");
    assert_eq!(unchanged["rerunArchitecture"], false);
    for i in 0..3 {
        fs::write(root.join(format!("docs/{i}.md")), "# Changed\n").unwrap();
    }
    let major = prepare(root, false).unwrap();
    assert_eq!(major["action"], "FULL_UPDATE");
    assert_eq!(major["rerunArchitecture"], true);
    assert_eq!(major["skipAssembleReviewer"], false);
}
