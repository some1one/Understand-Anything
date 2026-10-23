use serde_json::json;
use std::collections::BTreeSet;
use understand_anything::fingerprints::{classify_update,classify_update_with_inventory};
fn baseline() -> BTreeSet<String> {
    (0..20).map(|i| format!("src/file{i}.ts")).chain(["legacy/old.ts".into()]).collect()
}
#[test]
fn replacement_in_the_same_directory_is_not_a_directory_removal() {
    let before=baseline();
    let changes=vec![json!({"filePath":"legacy/old.ts","changeLevel":"STRUCTURAL","status":"deleted"}),json!({"filePath":"legacy/new.ts","changeLevel":"STRUCTURAL","status":"new"})];
    let result=classify_update(&changes,&before);
    assert_eq!(result["action"],"PARTIAL_UPDATE");
    assert_eq!(result["rerunArchitecture"],false);
    let deletion=classify_update(&changes[..1],&before);
    assert_eq!(deletion["action"],"ARCHITECTURE_UPDATE");
}
#[test]
fn explicit_after_inventory_drives_added_and_removed_directory_detection() {
    let before=baseline();
    let changes=vec![json!({"filePath":"legacy/old.ts","changeLevel":"STRUCTURAL","status":"deleted"})];
    let mut after=before.clone();after.remove("legacy/old.ts");after.insert("legacy/replacement.ts".into());
    assert_eq!(classify_update_with_inventory(&changes,&before,&after)["action"],"PARTIAL_UPDATE");
    after.remove("legacy/replacement.ts");after.insert("new-service/main.ts".into());
    let result=classify_update_with_inventory(&changes,&before,&after);
    assert_eq!(result["action"],"ARCHITECTURE_UPDATE");
    assert!(result["reason"].as_str().unwrap().contains("1 new, 1 removed"));
}
