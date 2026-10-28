use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
use understand_anything::{
    context_helpers,
    persistence::{publish_graph, write_json},
};

fn prepare_part(root: &Path, data_name: &str) -> (std::path::PathBuf, Vec<u8>) {
    let data = root.join(data_name);
    let inter = data.join("intermediate");
    fs::create_dir_all(inter.join("part-files")).unwrap();
    fs::create_dir_all(data.join("partitions")).unwrap();
    write_json(
        &data.join("config.json"),
        &json!({"splitDepth":1,"includedParts":["authentication"]}),
    )
    .unwrap();
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":[],"importMap":{},"failures":[]}),
    )
    .unwrap();
    write_json(&inter.join("part-files/authentication.json"), &json!([])).unwrap();
    write_json(
        &inter.join("assembled-graph.json"),
        &json!({"nodes":[],"edges":[]}),
    )
    .unwrap();
    let original = b"{\n  \"project\": {\"gitCommitHash\": \"old-revision\", \"custom\": true},\n  \"nodes\": [{\"id\":\"file:retired.md\",\"type\":\"file\",\"filePath\":\"retired.md\",\"summary\":\"full original evidence\"}],\n  \"edges\": [], \"layers\": [{\"id\":\"original-layer\"}]\n}\n".to_vec();
    let path = data.join("partitions/authentication.knowledge-graph.json");
    fs::write(&path, &original).unwrap();
    (path, original)
}
#[test]
fn native_part_publication_archives_complete_original_graph_and_reports_recovery_path() {
    for data_name in [".ua", ".understand-anything"] {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path();
        let (saved, original) = prepare_part(root, data_name);
        let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .args([
                "assemble_part_graph",
                root.to_str().unwrap(),
                "authentication",
            ])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let summary: Value = serde_json::from_slice(&output.stdout).unwrap();
        let archive = Path::new(summary["previousGraphPath"].as_str().unwrap());
        assert!(archive.starts_with(root.join(data_name).join("history/partitions")));
        assert_eq!(fs::read(archive).unwrap(), original);
        assert!(archive.parent().unwrap().join("recovery.json").is_file());
        assert!(archive.parent().unwrap().join("config.json").is_file());
        assert_eq!(
            serde_json::from_slice::<Value>(&fs::read(saved).unwrap()).unwrap()["nodes"],
            json!([])
        );
        assert!(
            !root
                .join(data_name)
                .join("intermediate/assembled-graph.json")
                .exists()
        );
    }
}
#[test]
fn failed_archive_preserves_published_graph_and_analysis_evidence() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let (saved, original) = prepare_part(root, ".ua");
    fs::write(root.join(".ua/history"), "blocked history directory").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args([
            "assemble_part_graph",
            root.to_str().unwrap(),
            "authentication",
        ])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert_eq!(fs::read(saved).unwrap(), original);
    assert!(root.join(".ua/intermediate/assembled-graph.json").is_file());
}
#[test]
fn merged_publication_and_repeated_updates_keep_independent_full_snapshots() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    fs::create_dir_all(root.join(".ua/intermediate")).unwrap();
    let first = json!({"project":{"gitCommitHash":"first"},"nodes":[],"edges":[],"extra":{"keep":"all metadata"}});
    let second = json!({"project":{"gitCommitHash":"second"},"nodes":[],"edges":[]});
    let third = json!({"project":{"gitCommitHash":"third"},"nodes":[],"edges":[]});
    assert!(
        publish_graph(root, "knowledge-graph.json", &first)
            .unwrap()
            .is_none()
    );
    let first_bytes = fs::read(root.join(".ua/knowledge-graph.json")).unwrap();
    write_json(&root.join(".ua/intermediate/assembled-graph.json"), &second).unwrap();
    let summary = context_helpers::save_knowledge_graph(root).unwrap();
    let first_archive = Path::new(summary["previousGraphPath"].as_str().unwrap());
    assert_eq!(fs::read(first_archive).unwrap(), first_bytes);
    let second_archive = publish_graph(root, "knowledge-graph.json", &third)
        .unwrap()
        .unwrap();
    assert_ne!(first_archive, second_archive);
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(second_archive).unwrap()).unwrap(),
        second
    );
    assert_eq!(fs::read(first_archive).unwrap(), first_bytes);
    assert!(publish_graph(root, "../outside.json", &third).is_err());
}
