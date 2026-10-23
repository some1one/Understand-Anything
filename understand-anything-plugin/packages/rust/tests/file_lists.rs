use serde_json::json;
use std::fs;
use understand_anything::{file_lists, persistence::write_json};

#[test]
fn json_handoffs_preserve_names_and_reject_invalid_lists() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("changed.JSON");
    let names = vec![" leading.py", "trailing.py ", "line\nreturn\r.py", "a\\b.py", "文.py"];
    write_json(&path, &json!(names)).unwrap();
    assert_eq!(file_lists::read(&path).unwrap(), names);
    for invalid in ["", "{}", "[1]", "[null]", "[\"unterminated"] {
        fs::write(&path, invalid).unwrap();
        assert!(file_lists::read(&path).is_err(), "{invalid}");
    }
    let legacy = temp.path().join("old.txt");
    fs::write(&legacy, " first.py\nlast.py \n").unwrap();
    assert_eq!(file_lists::read(&legacy).unwrap(), [" first.py", "last.py "]);
    fs::write(&legacy, "line\nname.py\0other.py\0").unwrap();
    assert_eq!(file_lists::read(&legacy).unwrap(), ["line\nname.py", "other.py"]);
    fs::write(&legacy, "[\"embedded\\nname.py\"]").unwrap();
    assert_eq!(file_lists::read(&legacy).unwrap(), ["embedded\nname.py"]);
}

#[test]
fn partition_cli_writes_lossless_json_lists() {
    let temp = tempfile::tempdir().unwrap();
    let inter = temp.path().join(".ua/intermediate");
    fs::create_dir_all(&inter).unwrap();
    let names = ["src/line\nname.py", "src/ leading.py", "src/a\\b.py"];
    write_json(&inter.join("scan-result.json"), &json!({"files":names.iter().map(|path| json!({"path":path})).collect::<Vec<_>>()})).unwrap();
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("partition_files").arg(temp.path()).arg("--depth=1").output().unwrap();
    assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
    let mut actual = file_lists::read(&inter.join("part-files/src.json")).unwrap();
    actual.sort();
    let mut expected = names.iter().map(|name| understand_anything::imports::to_posix(name)).collect::<Vec<_>>(); expected.sort();
    assert_eq!(actual, expected);
}

#[test]
fn batching_uses_json_targets_and_leaves_output_on_invalid_input() {
    let temp = tempfile::tempdir().unwrap();
    let inter = temp.path().join(".ua/intermediate");
    fs::create_dir_all(&inter).unwrap();
    let target = "docs/line\nname.md";
    write_json(&inter.join("scan-result.json"), &json!({"files":[
        {"path":target,"language":"markdown","fileCategory":"docs"},
        {"path":"docs/other.md","language":"markdown","fileCategory":"docs"}
    ]})).unwrap();
    let list = inter.join("changed.json");
    write_json(&list, &json!([target])).unwrap();
    let run = || std::process::Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("compute_batches").arg(temp.path()).arg("--changed-files").arg(&list).output().unwrap();
    let result = run();
    assert!(result.status.success(), "{}", String::from_utf8_lossy(&result.stderr));
    let output = inter.join("batches.json");
    let before = fs::read(&output).unwrap();
    let batches: serde_json::Value = serde_json::from_slice(&before).unwrap();
    let paths = batches["batches"].as_array().unwrap().iter().flat_map(|b| b["files"].as_array().unwrap()).map(|f| f["path"].as_str().unwrap()).collect::<Vec<_>>();
    assert_eq!(paths, [target]);
    fs::write(&list, "[42]").unwrap();
    assert!(!run().status.success());
    assert_eq!(fs::read(&output).unwrap(), before);
}
