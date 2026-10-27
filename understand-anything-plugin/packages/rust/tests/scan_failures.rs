use std::{fs, process::Command};
use understand_anything::scan::scan_project;

#[test]
fn scan_reports_tracked_files_missing_from_the_worktree() {
    let temp = tempfile::tempdir().unwrap();
    for args in [vec!["init", "-q"], vec!["config", "user.email", "test@example.com"], vec!["config", "user.name", "Test"]] {
        assert!(Command::new("git").args(args).current_dir(temp.path()).status().unwrap().success());
    }
    fs::write(temp.path().join("source.rb"), "puts 'hello'").unwrap();
    assert!(Command::new("git").args(["add", "source.rb"]).current_dir(temp.path()).status().unwrap().success());
    fs::rename(temp.path().join("source.rb"), temp.path().join("moved.rb")).unwrap();
    let scan = scan_project(temp.path()).unwrap();
    assert_eq!(scan["failures"][0]["path"], "source.rb");
    assert_eq!(scan["failures"][0]["stage"], "file-stat");
    assert_eq!(scan["files"][0]["path"], "moved.rb");
}

#[test]
fn scan_reports_failed_enumeration_instead_of_a_clean_empty_inventory() {
    let temp = tempfile::tempdir().unwrap();
    let scan = scan_project(&temp.path().join("missing")).unwrap();
    assert_eq!(scan["failures"][0]["stage"], "enumeration");
    assert_eq!(scan["totalFiles"], 0);
}

#[test]
fn ignore_reconciliation_stops_on_scan_failure_without_advancing_baseline() {
    use understand_anything::{persistence, updates::{GitClient, preflight_with_git}};
    use serde_json::json;
    struct Git;
    impl GitClient for Git {
        fn head(&self, _: &std::path::Path) -> Option<String> { Some("next".into()) }
        fn changed_files(&self, _: &std::path::Path, _: &str, _: &str) -> Option<Vec<String>> {
            Some(vec![".uaignore".into()])
        }
    }
    for directory in [".ua", ".understand-anything"] {
        let temp = tempfile::tempdir().unwrap();
        fs::create_dir(temp.path().join(directory)).unwrap();
        persistence::save_meta(temp.path(), &json!({"gitCommitHash":"baseline"})).unwrap();
        let data = persistence::data_dir(temp.path());
        let graph = r#"{"nodes":[{"id":"file:source.rb","type":"file","filePath":"source.rb"}],"edges":[]}"#;
        fs::write(data.join("knowledge-graph.json"), graph).unwrap();
        let meta = fs::read(data.join("meta.json")).unwrap();
        assert!(Command::new("git").args(["init", "-q"]).current_dir(temp.path()).status().unwrap().success());
        fs::write(temp.path().join("source.rb"), "puts 'hello'").unwrap();
        assert!(Command::new("git").args(["add", "source.rb"]).current_dir(temp.path()).status().unwrap().success());
        fs::rename(temp.path().join("source.rb"), data.join("saved.rb")).unwrap();
        let state = preflight_with_git(temp.path(), false, &Git).unwrap();
        assert_eq!(state["action"], "SCAN_FAILED", "{state}");
        assert_eq!(state["status"], "STOP");
        assert_eq!(state["metadataUpdated"], false);
        assert_eq!(state["scanFailures"][0]["path"], "source.rb");
        assert_eq!(fs::read(data.join("meta.json")).unwrap(), meta);
        assert_eq!(fs::read_to_string(data.join("knowledge-graph.json")).unwrap(), graph);
        // Once the source is readable, the same reconciliation can proceed.
        fs::rename(data.join("saved.rb"), temp.path().join("source.rb")).unwrap();
        let state = preflight_with_git(temp.path(), false, &Git).unwrap();
        assert_eq!(state["action"], "PROCEED", "{state}");
        assert_eq!(state["changedSourceFiles"], json!(["source.rb"]));
    }
}
