use serde_json::json;
use std::collections::BTreeSet;
use understand_anything::fingerprints::{classify_update, classify_update_with_inventory};
fn baseline() -> BTreeSet<String> {
    (0..20)
        .map(|i| format!("src/file{i}.ts"))
        .chain(["legacy/old.ts".into()])
        .collect()
}
#[test]
fn replacement_in_the_same_directory_is_not_a_directory_removal() {
    let before = baseline();
    let changes = vec![
        json!({"filePath":"legacy/old.ts","changeLevel":"STRUCTURAL","status":"deleted"}),
        json!({"filePath":"legacy/new.ts","changeLevel":"STRUCTURAL","status":"new"}),
    ];
    let result = classify_update(&changes, &before);
    assert_eq!(result["action"], "PARTIAL_UPDATE");
    assert_eq!(result["rerunArchitecture"], false);
    let deletion = classify_update(&changes[..1], &before);
    assert_eq!(deletion["action"], "ARCHITECTURE_UPDATE");
}
#[test]
fn explicit_after_inventory_drives_added_and_removed_directory_detection() {
    let before = baseline();
    let changes =
        vec![json!({"filePath":"legacy/old.ts","changeLevel":"STRUCTURAL","status":"deleted"})];
    let mut after = before.clone();
    after.remove("legacy/old.ts");
    after.insert("legacy/replacement.ts".into());
    assert_eq!(
        classify_update_with_inventory(&changes, &before, &after)["action"],
        "PARTIAL_UPDATE"
    );
    after.remove("legacy/replacement.ts");
    after.insert("new-service/main.ts".into());
    let result = classify_update_with_inventory(&changes, &before, &after);
    assert_eq!(result["action"], "ARCHITECTURE_UPDATE");
    assert!(
        result["reason"]
            .as_str()
            .unwrap()
            .contains("1 new, 1 removed")
    );
}

#[test]
fn fingerprint_phase_reconciles_scope_changes_missing_from_git_paths() {
    use std::fs;
    use understand_anything::{fingerprints, persistence::write_json, updates};
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    fs::create_dir_all(root.join(".ua/intermediate")).unwrap();
    fs::create_dir(root.join("docs")).unwrap();
    let old: Vec<_> = (0..7).map(|i| format!("docs/{i}.md")).collect();
    for path in &old {
        fs::write(root.join(path), "# Unchanged\n").unwrap();
    }
    write_json(
        &root.join(".ua/fingerprints.json"),
        &fingerprints::build_fingerprint_store(root, &old, "base"),
    )
    .unwrap();
    write_json(&root.join(".ua/knowledge-graph.json"),&json!({"nodes":old.iter().map(|path|json!({"id":path,"type":"document","filePath":path})).collect::<Vec<_>>(),"edges":[]})).unwrap();
    // The excluded file still exists, and the newly inventoried file is absent
    // from the supplied Git list. Neither condition is a source deletion/edit.
    write_json(
        &root.join(".ua/meta.json"),
        &json!({"excludePatterns":["docs/0.md"]}),
    )
    .unwrap();
    fs::write(root.join("docs/new.md"), "# Newly included\n").unwrap();
    fs::write(root.join("outside.ps1"), "Write-Host ignored").unwrap();
    write_json(
        &root.join(".ua/intermediate/auto-update-state.json"),
        &json!({"changedSourceFiles":["outside.ps1"]}),
    )
    .unwrap();
    let graph_before = fs::read(root.join(".ua/knowledge-graph.json")).unwrap();
    let result = updates::fingerprint_check(root).unwrap();
    assert_eq!(result["filesToReanalyze"], json!(["docs/new.md"]));
    assert_eq!(result["deletedFiles"], json!(["docs/0.md"]));
    assert_eq!(result["action"], "PARTIAL_UPDATE");
    assert_eq!(result["rerunArchitecture"], false);
    assert_eq!(
        fs::read(root.join(".ua/knowledge-graph.json")).unwrap(),
        graph_before
    );
    write_json(&root.join(".ua/intermediate/change-analysis.json"), &result).unwrap();
    let batches = updates::prepare_batches(root).unwrap();
    assert_eq!(batches["filesToReanalyze"], json!(["docs/new.md"]));
    assert!(
        !batches["allProjectFiles"]
            .as_array()
            .unwrap()
            .contains(&json!("docs/0.md"))
    );
}
