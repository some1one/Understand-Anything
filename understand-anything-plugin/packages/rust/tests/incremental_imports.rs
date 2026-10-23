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
    write_json(&temp.path().join(".ua/knowledge-graph.json"), &json!({"nodes":[
        {"id":"file:main.rb","type":"file","filePath":"main.rb"}
    ],"edges":[]})).unwrap();
    save(&temp, "batch-0.json", json!({"nodes":[
        {"id":"file:dep.rb","type":"file","filePath":"dep.rb"}
    ],"edges":[]}));
    let graph = understand_anything::updates::apply_batches(temp.path()).unwrap();
    assert!(graph["edges"].as_array().unwrap().iter().any(|e|
        e["source"] == "file:main.rb" && e["target"] == "file:dep.rb" && e["type"] == "imports"));
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

#[test]
fn preparation_reuses_published_scope_instead_of_an_abandoned_scan_scope() {
    let temp = setup();
    fs::create_dir(temp.path().join("docs")).unwrap();
    fs::write(temp.path().join("main.rb"),"require_relative 'docs/hidden'\n").unwrap();
    fs::write(temp.path().join("docs/hidden.rb"),"puts 'hidden'\n").unwrap();
    write_json(&temp.path().join(".ua/meta.json"),&json!({"excludePatterns":["docs/"]})).unwrap();
    save(&temp,"scan-result.json",json!({"excludePatterns":["other/"],"files":[],"importMap":{}}));
    save(&temp,"change-analysis.json",json!({"filesToReanalyze":["main.rb"]}));
    prepare_batches(temp.path()).unwrap();
    assert_eq!(scan(&temp)["excludePatterns"],json!(["docs/"]));
    assert_eq!(scan(&temp)["importMap"],json!({"main.rb":[]}));
    write_json(&temp.path().join(".ua/meta.json"),&json!({})).unwrap();
    prepare_batches(temp.path()).unwrap();
    assert!(scan(&temp).get("excludePatterns").is_none());
    assert_eq!(scan(&temp)["importMap"]["main.rb"],json!(["docs/hidden.rb"]));
}

#[test]
fn replacement_head_uses_original_scan_instead_of_abandoned_imports() {
    use std::process::Command;
    let temp = setup();
    let root = temp.path();
    let git = |args: &[&str]| {
        let output = Command::new("git").args(args).current_dir(root).output().unwrap();
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        String::from_utf8(output.stdout).unwrap().trim().to_owned()
    };
    git(&["init", "-q"]);
    git(&["config", "user.name", "Test"]);
    git(&["config", "user.email", "test@example.com"]);
    fs::write(root.join("main.rb"), "require_relative 'a'\n").unwrap();
    for name in ["a.rb", "b.rb", "c.rb"] { fs::write(root.join(name), "puts 'base'\n").unwrap(); }
    git(&["add", "*.rb"]); git(&["commit", "-qm", "base"]);
    let base = git(&["rev-parse", "HEAD"]);
    let original = json!({"files":[{"path":"main.rb"},{"path":"a.rb"},{"path":"b.rb"},{"path":"c.rb"}],
        "importMap":{"main.rb":["a.rb"],"a.rb":[],"b.rb":[],"c.rb":[]}});
    save(&temp, "scan-result.json", original.clone());
    fs::write(root.join("main.rb"), "require_relative 'b'\n").unwrap();
    git(&["add", "main.rb"]); git(&["commit", "-qm", "abandoned"]);
    save(&temp, "auto-update-state.json", json!({"previousCommit":base,"currentCommit":git(&["rev-parse","HEAD"])}));
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":["main.rb"]}));
    prepare_batches(root).unwrap();
    assert_eq!(scan(&temp)["importMap"]["main.rb"], json!(["b.rb"]));
    let snapshot_path = root.join(".ua/intermediate/incremental-scan-baseline.json");
    let snapshot = fs::read(&snapshot_path).unwrap();
    assert_eq!(read_json(&snapshot_path).unwrap()["scan"], original);
    git(&["checkout", "-qb", "replacement", &base]);
    fs::write(root.join("c.rb"), "puts 'changed'\n").unwrap();
    git(&["add", "c.rb"]); git(&["commit", "-qm", "replacement"]);
    save(&temp, "auto-update-state.json", json!({"previousCommit":base,"currentCommit":git(&["rev-parse","HEAD"])}));
    save(&temp, "change-analysis.json", json!({"filesToReanalyze":["c.rb"]}));
    prepare_batches(root).unwrap();
    assert_eq!(scan(&temp)["importMap"]["main.rb"], json!(["a.rb"]));
    assert_eq!(fs::read(&snapshot_path).unwrap(), snapshot);
    prepare_batches(root).unwrap();
    assert_eq!(scan(&temp)["importMap"]["main.rb"], json!(["a.rb"]));
    assert_eq!(fs::read(&snapshot_path).unwrap(), snapshot);
    // A malformed saved baseline must not silently fall back to mutable output.
    fs::write(&snapshot_path, "{").unwrap();
    let before = fs::read(root.join(".ua/intermediate/scan-result.json")).unwrap();
    assert!(prepare_batches(root).is_err());
    assert_eq!(fs::read(root.join(".ua/intermediate/scan-result.json")).unwrap(), before);
}
