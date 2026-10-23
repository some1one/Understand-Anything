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

#[test]
fn coverage_accounts_for_unsupported_and_unreadable_without_changing_results() {
    let temp = tempfile::tempdir().unwrap();
    fs::write(temp.path().join("README.md"), "# Title\n").unwrap();
    fs::write(temp.path().join("file.unknown"), "hello").unwrap();
    let mut input = json!({"projectRoot":temp.path(),"batchFiles":[
        {"path":"README.md","language":"markdown","fileCategory":"docs"},
        {"path":"file.unknown","language":"unknown","fileCategory":"code"},
        {"path":"missing.py","language":"python","fileCategory":"code"}],"batchImportData":{}});
    let normal = understand_anything::structure::extract_structure(&input).unwrap();
    input["includeCoverage"] = json!(true);
    let mut measured = understand_anything::structure::extract_structure(&input).unwrap();
    let evidence = measured.as_object_mut().unwrap().remove("coverage").unwrap();
    assert_eq!(normal, measured);
    assert_eq!(evidence[0]["structure"], "succeeded");
    assert_eq!(evidence[0]["callGraph"], "unsupported");
    assert_eq!(evidence[1]["structure"], "unsupported");
    assert_eq!(evidence[2]["structure"], "unreadable");
}
