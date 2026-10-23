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
