use serde_json::{Value, json};
use std::fs;
use understand_anything::{persistence::{read_json, write_json}, updates::prepare_batches};

fn setup() -> tempfile::TempDir {
    let temp = tempfile::tempdir().unwrap();
    fs::create_dir_all(temp.path().join(".ua/intermediate")).unwrap();
    temp
}
fn save(temp: &tempfile::TempDir, name: &str, value: Value) {
    write_json(&temp.path().join(".ua/intermediate").join(name), &value).unwrap();
}
fn scan(temp: &tempfile::TempDir) -> Value {
    read_json(&temp.path().join(".ua/intermediate/scan-result.json")).unwrap()
}
#[test]
fn new_targets_refresh_imports_in_unchanged_files() {
    let temp = setup();
    fs::write(temp.path().join("main.rb"), "require_relative 'dep'\n").unwrap();
    save(&temp, "scan-result.json", json!({"files":[{"path":"main.rb"}],"importMap":{"main.rb":[]}}));
    fs::write(temp.path().join("dep.rb"), "puts 'hello'\n").unwrap();
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":["dep.rb"]}));
    prepare_batches(temp.path()).unwrap();
    assert_eq!(scan(&temp)["importMap"]["main.rb"], json!(["dep.rb"]));
    // A committed deletion disappears from both the inventory and import targets.
    fs::rename(temp.path().join("dep.rb"), temp.path().join(".ua/dep.rb")).unwrap();
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":[],"deletedFiles":["dep.rb"]}));
    prepare_batches(temp.path()).unwrap();
    let result = scan(&temp);
    assert_eq!(result["importMap"], json!({"main.rb":[]}));
}
#[test]
fn import_failure_preserves_previous_preparation_outputs() {
    let temp = setup();
    fs::write(temp.path().join("main.rb"), [0xff]).unwrap();
    let old = json!({"files":[{"path":"main.rb"}],"importMap":{"main.rb":[]}});
    save(&temp, "scan-result.json", old.clone());
    save(&temp, "batches.json", json!({"previous":true}));
    save(&temp, "dispatch-summary.json", json!({"previous":true}));
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":["main.rb"]}));
    assert!(prepare_batches(temp.path()).is_err());
    assert_eq!(scan(&temp), old);
    for name in ["batches.json", "dispatch-summary.json"] {
        assert_eq!(read_json(&temp.path().join(".ua/intermediate").join(name)).unwrap(), json!({"previous":true}));
    }
}
#[test]
fn missing_analysis_target_is_not_silently_dropped() {
    let temp = setup();
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":["missing.rb"]}));
    let error = prepare_batches(temp.path()).unwrap_err().to_string();
    assert!(error.contains("missing.rb"), "{error}");
    assert!(!temp.path().join(".ua/intermediate/batches.json").exists());
}

#[test]
fn unchanged_inventory_reuses_unchanged_imports_but_refreshes_changed_sources() {
    let temp = setup();
    // The scanner counts bytes; an unselected source need not be decoded again.
    fs::write(temp.path().join("unchanged.rb"), [0xff]).unwrap();
    fs::write(temp.path().join("changed.rb"), "require_relative 'unchanged'\n").unwrap();
    save(&temp, "scan-result.json", json!({"files":[{"path":"unchanged.rb"},{"path":"changed.rb"}],
        "importMap":{"unchanged.rb":["changed.rb"],"changed.rb":[]}}));
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":["changed.rb"]}));
    prepare_batches(temp.path()).unwrap();
    assert_eq!(scan(&temp)["importMap"], json!({"unchanged.rb":["changed.rb"],"changed.rb":["unchanged.rb"]}));
}
