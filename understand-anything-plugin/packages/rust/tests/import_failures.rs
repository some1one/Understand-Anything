use serde_json::json;
use std::{fs, process::Command};
use understand_anything::imports::extract_import_map;

#[test]
fn unreadable_import_source_aborts_without_overwriting_previous_output() {
    let temp = tempfile::tempdir().unwrap();
    let input = json!({"projectRoot":temp.path(),"files":[
        {"path":"gone.ts","language":"typescript","fileCategory":"code"}
    ]});
    let error = extract_import_map(&input).unwrap_err().to_string();
    assert!(error.contains("gone.ts") && error.contains("read error"), "{error}");
    let input_path = temp.path().join("input.json");
    let output_path = temp.path().join("output.json");
    fs::write(&input_path, input.to_string()).unwrap();
    let previous = r#"{"importMap":{"gone.ts":["dep.ts"]}}"#;
    fs::write(&output_path, previous).unwrap();
    let result = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("extract_import_map").arg(&input_path).arg(&output_path)
        .output().unwrap();
    assert!(!result.status.success());
    assert_eq!(fs::read_to_string(output_path).unwrap(), previous);
}

#[test]
fn invalid_utf8_is_a_read_failure_and_unselected_files_are_not_read() {
    let temp = tempfile::tempdir().unwrap();
    fs::write(temp.path().join("bad.rb"), [0xff]).unwrap();
    fs::write(temp.path().join("good.rb"), "require_relative 'dep'\n").unwrap();
    let mut input = json!({"projectRoot":temp.path(),"files":[
        {"path":"bad.rb","language":"ruby","fileCategory":"code"},
        {"path":"good.rb","language":"ruby","fileCategory":"code"},
        {"path":"dep.rb","language":"ruby","fileCategory":"code"}
    ]});
    assert!(extract_import_map(&input).unwrap_err().to_string().contains("bad.rb"));
    input["analysisPaths"] = json!(["good.rb"]);
    let result = extract_import_map(&input).unwrap();
    assert_eq!(result["importMap"], json!({"good.rb":["dep.rb"]}));
}
