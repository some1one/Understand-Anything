use serde_json::json;
use understand_anything::fingerprints::{compare_fingerprints, fingerprint_for_content};

#[test]
fn noncode_changes_enter_preflight_without_advancing_metadata() {
    use std::{fs, path::Path};
    use understand_anything::{persistence, updates};
    struct Git;
    impl updates::GitClient for Git {
        fn head(&self, _: &Path) -> Option<String> {
            Some("new".into())
        }
        fn changed_files(&self, _: &Path, _: &str, _: &str) -> Option<Vec<String>> {
            Some(vec![
                "README.md".into(),
                "config.yaml".into(),
                "deleted.csv".into(),
            ])
        }
    }
    let tmp = tempfile::tempdir().unwrap();
    persistence::save_meta(tmp.path(), &json!({"gitCommitHash":"old"})).unwrap();
    let dir = persistence::data_dir(tmp.path());
    fs::write(
        dir.join("knowledge-graph.json"),
        r#"{"nodes":[],"edges":[]}"#,
    )
    .unwrap();
    let state = updates::preflight_with_git(tmp.path(), false, &Git).unwrap();
    assert_eq!(state["action"], "PROCEED");
    assert_eq!(
        state["changedSourceFiles"],
        json!(["README.md", "config.yaml", "deleted.csv"])
    );
    assert_eq!(state["metadataUpdated"], false);
    assert_eq!(
        persistence::load_meta(tmp.path()).unwrap().unwrap()["gitCommitHash"],
        "old"
    );
}

#[test]
fn noncode_edits_are_conservative_even_when_declaration_signatures_are_empty() {
    for (path, before, after) in [
        ("config.yaml", "port: 80\n", "port: 443\n"),
        ("package.json", "{\"private\":false}", "{\"private\":true}"),
        ("README.md", "# Before\n", "# After\n"),
        ("Dockerfile", "FROM alpine:3.21\n", "FROM alpine:3.22\n"),
        (
            "schema.graphql",
            "type User { id: ID }",
            "type User { name: String }",
        ),
        ("data.csv", "key,value\na,1\n", "key,value\na,2\n"),
    ] {
        let old = fingerprint_for_content(path, before);
        let new = fingerprint_for_content(path, after);
        assert_eq!(new["hasStructuralAnalysis"], false, "{path}");
        assert_eq!(compare_fingerprints(&old, &new).0, "STRUCTURAL", "{path}");
        assert_eq!(compare_fingerprints(&new, &new).0, "NONE", "{path}");
        // A baseline produced by the previous implementation must also refresh.
        let mut legacy = old;
        legacy["hasStructuralAnalysis"] = json!(true);
        assert_eq!(
            compare_fingerprints(&legacy, &new).0,
            "STRUCTURAL",
            "{path}"
        );
    }
}
