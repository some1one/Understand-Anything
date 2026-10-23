use serde_json::json;
use std::fs;
use understand_anything::{persistence, scan};

#[test]
fn new_projects_use_ua_without_creating_directories_on_read() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    assert_eq!(persistence::data_dir(root), root.join(".ua"));
    assert!(persistence::load_meta(root).unwrap().is_none());
    assert!(!root.join(".ua").exists());
    persistence::save_meta(root, &json!({"gitCommitHash":"new"})).unwrap();
    assert!(root.join(".ua/meta.json").is_file());
    assert!(!root.join(".understand-anything").exists());
}

#[test]
fn legacy_projects_stay_in_place_and_current_directory_wins_as_a_unit() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    fs::create_dir(root.join(".understand-anything")).unwrap();
    persistence::save_meta(root, &json!({"gitCommitHash":"legacy"})).unwrap();
    assert!(root.join(".understand-anything/meta.json").is_file());
    assert!(!root.join(".ua").exists());
    fs::create_dir(root.join(".ua")).unwrap();
    // Missing optional artifacts must not be borrowed from a different graph.
    assert!(persistence::load_meta(root).unwrap().is_none());
    persistence::save_config(root, &json!({"autoUpdate":true})).unwrap();
    assert!(root.join(".ua/config.json").is_file());
    assert!(!root.join(".understand-anything/config.json").exists());
}

#[test]
fn scanner_excludes_both_artifact_directories_and_reads_selected_ignore() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    fs::create_dir(root.join(".ua")).unwrap();
    fs::create_dir(root.join(".understand-anything")).unwrap();
    fs::write(root.join(".ua/.understandignore"), "current.txt\n").unwrap();
    fs::write(
        root.join(".understand-anything/.understandignore"),
        "legacy.txt\n",
    )
    .unwrap();
    let filter = scan::create_ignore_filter(root).unwrap();
    assert!(filter.is_ignored(".ua/knowledge-graph.json"));
    assert!(filter.is_ignored(".understand-anything/knowledge-graph.json"));
    assert!(filter.is_ignored("current.txt"));
    assert!(!filter.is_ignored("legacy.txt"));
}
