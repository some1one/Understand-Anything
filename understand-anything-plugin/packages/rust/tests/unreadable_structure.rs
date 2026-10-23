use serde_json::{Value, json};
use std::{fs, process::Command};
use understand_anything::{batch_validation, structure};

fn input(root: &std::path::Path, paths: &[&str]) -> Value {
    json!({"projectRoot":root,"batchFiles": paths.iter().map(|path| json!({"path":path,"fileCategory":"data"})).collect::<Vec<_>>()})
}

#[test]
fn mixed_batch_distinguishes_read_failure_from_readable_unknown_language() {
    let tmp = tempfile::tempdir().unwrap();
    fs::write(tmp.path().join("readable.xyz"), "no registered parser").unwrap();
    fs::write(tmp.path().join("invalid.xyz"), [0xff, 0xfe]).unwrap();
    let request = input(tmp.path(), &["readable.xyz", "missing.xyz", "invalid.xyz"]);
    let result = structure::extract_structure(&request).unwrap();
    assert_eq!(result["filesAnalyzed"], 1);
    assert_eq!(result["results"][0]["path"], "readable.xyz");
    assert_eq!(
        result["filesSkipped"],
        json!(["missing.xyz", "invalid.xyz"])
    );
    assert_eq!(
        result["filesUnreadable"],
        json!([
            {"path":"missing.xyz","code":"ENOENT"},
            {"path":"invalid.xyz","code":"EILSEQ"}
        ])
    );
    let issues = batch_validation::check_structure_output(&request, &result);
    assert_eq!(issues.len(), 2, "{issues:?}");
    assert!(
        issues
            .iter()
            .all(|issue| issue.contains("could not be read"))
    );

    let extraction = tmp.path().join("extraction.json");
    fs::write(&extraction, result.to_string()).unwrap();
    let output = tmp.path().join("seed.json");
    let run = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("seed_file_batch_graph")
        .arg(tmp.path().join("context.json"))
        .arg(extraction)
        .arg(&output)
        .output()
        .unwrap();
    assert!(!run.status.success());
    assert!(String::from_utf8_lossy(&run.stderr).contains("unreadable"));
    assert!(!output.exists());
}

#[test]
fn cli_preserves_diagnostics_and_fails_only_nonempty_entirely_unreadable_batches() {
    let tmp = tempfile::tempdir().unwrap();
    fs::write(tmp.path().join("readable.xyz"), "data").unwrap();
    for (paths, success) in [
        (vec![], true),
        (vec!["missing.xyz"], false),
        (vec!["readable.xyz", "missing.xyz"], true),
        (vec!["readable.xyz"], true),
    ] {
        let request = tmp.path().join("input.json");
        let output = tmp.path().join("output.json");
        fs::write(&request, input(tmp.path(), &paths).to_string()).unwrap();
        let run = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .arg("extract_structure")
            .arg(&request)
            .arg(&output)
            .output()
            .unwrap();
        assert_eq!(run.status.success(), success, "{paths:?}");
        let result: Value = serde_json::from_slice(&fs::read(&output).unwrap()).unwrap();
        let failures = result["filesUnreadable"].as_array().unwrap();
        assert_eq!(!failures.is_empty(), paths.contains(&"missing.xyz"));
        assert_eq!(!run.stderr.is_empty(), !failures.is_empty());
    }
}
