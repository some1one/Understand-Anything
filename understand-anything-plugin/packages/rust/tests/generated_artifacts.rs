use serde_json::json;
use std::{fs, path::Path};
use understand_anything::{
    persistence,
    updates::{GitClient, preflight_with_git},
};

struct Git(Vec<String>);
impl GitClient for Git {
    fn head(&self, _: &Path) -> Option<String> {
        Some("next".into())
    }
    fn changed_files(&self, _: &Path, _: &str, _: &str) -> Option<Vec<String>> {
        Some(self.0.clone())
    }
}

#[test]
fn generated_only_commits_preserve_metadata_bytes_in_both_directory_modes() {
    for directory in [".ua", ".understand-anything"] {
        let tmp = tempfile::tempdir().unwrap();
        let dir = tmp.path().join(directory);
        fs::create_dir(&dir).unwrap();
        fs::write(
            dir.join("knowledge-graph.json"),
            r#"{"nodes":[],"edges":[]}"#,
        )
        .unwrap();
        let metadata = r#"{"gitCommitHash":"baseline","lastAnalyzedAt":"unchanged"}"#;
        fs::write(dir.join("meta.json"), metadata).unwrap();
        for force in [false, true] {
            let git = Git(vec![
                ".ua/meta.json".into(),
                ".understand-anything/tmp/generated.rs".into(),
            ]);
            let state = preflight_with_git(tmp.path(), force, &git).unwrap();
            assert_eq!(state["action"], "GENERATED_ONLY");
            assert_eq!(state["status"], "STOP");
            assert_eq!(state["metadataUpdated"], false);
            assert_eq!(fs::read_to_string(dir.join("meta.json")).unwrap(), metadata);
        }
    }
}

#[test]
fn artifact_filter_preserves_source_changes_ignore_rules_and_directory_boundaries() {
    let tmp = tempfile::tempdir().unwrap();
    persistence::save_meta(tmp.path(), &json!({"gitCommitHash":"baseline"})).unwrap();
    let dir = persistence::data_dir(tmp.path());
    fs::write(
        dir.join("knowledge-graph.json"),
        r#"{"nodes":[],"edges":[]}"#,
    )
    .unwrap();
    for changed in [
        vec![".ua/meta.json", "src/main.rs"],
        vec![".ua-tools/main.rs"],
    ] {
        let state = preflight_with_git(
            tmp.path(),
            false,
            &Git(changed.iter().map(|s| s.to_string()).collect()),
        )
        .unwrap();
        assert_eq!(state["action"], "PROCEED");
        assert_eq!(
            state["changedSourceFiles"],
            json!([changed.last().unwrap()])
        );
        assert_eq!(state["metadataUpdated"], false);
    }
    fs::write(tmp.path().join("main.rs"), "fn main() {}\n").unwrap();
    let state = preflight_with_git(
        tmp.path(),
        false,
        &Git(vec![".ua/.understandignore".into()]),
    )
    .unwrap();
    assert_eq!(state["action"], "PROCEED");
    assert!(
        state["changedSourceFiles"]
            .as_array()
            .unwrap()
            .contains(&json!("main.rs"))
    );
    assert_eq!(state["metadataUpdated"], false);
}

#[test]
fn automatic_preflight_keeps_published_exclusions_and_negations() {
    let tmp = tempfile::tempdir().unwrap(); let root = tmp.path();
    persistence::save_meta(root, &json!({"gitCommitHash":"baseline","excludePatterns":["docs/","!docs/keep.md"]})).unwrap();
    persistence::save_artifact(root,"knowledge-graph.json",&json!({"nodes":[],"edges":[]})).unwrap();
    let ignored = preflight_with_git(root,false,&Git(vec!["docs/other.md".into()])).unwrap();
    assert_eq!(ignored["action"],"ALL_IGNORED");
    assert_eq!(persistence::load_meta(root).unwrap().unwrap()["excludePatterns"],json!(["docs/","!docs/keep.md"]));
    let included = preflight_with_git(root,true,&Git(vec!["docs/keep.md".into()])).unwrap();
    assert_eq!(included["action"],"PROCEED");
    persistence::save_meta(root,&json!({"gitCommitHash":"baseline","excludePatterns":"corrupt"})).unwrap();
    assert!(preflight_with_git(root,true,&Git(vec!["src/main.rs".into()])).is_err());
}
