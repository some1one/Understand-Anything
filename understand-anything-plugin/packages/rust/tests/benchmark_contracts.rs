use serde_json::json;
use std::{fs, process::Command};

#[test]
fn batch_cli_uses_explicit_artifacts_without_subject_writes() {
    let temp = tempfile::tempdir().unwrap();
    let subject = temp.path().join("subject");
    fs::create_dir(&subject).unwrap();
    let scan = temp.path().join("scan.json");
    let output = temp.path().join("batches.json");
    fs::write(&scan, json!({"files":[],"importMap":{}}).to_string()).unwrap();
    let status = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args(["--offline-parsers", "compute_batches"])
        .arg(&subject).arg("--scan-result").arg(&scan).arg("--output").arg(&output)
        .status().unwrap();
    assert!(status.success());
    let result: serde_json::Value = serde_json::from_slice(&fs::read(output).unwrap()).unwrap();
    assert_eq!(result["batches"], json!([]));
    assert_eq!(fs::read_dir(subject).unwrap().count(), 0);
}
