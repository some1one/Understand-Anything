use std::{fs, path::Path, process::Command};
use serde_json::json;
use understand_anything::{updates::{self, ProcessGit, GitClient}, persistence::write_json};
fn git(root: &Path, args: &[&str]) {
    assert!(Command::new("git").args(args).current_dir(root).output().unwrap().status.success());
}
fn setup() -> tempfile::TempDir {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    git(root, &["init", "-q"]); git(root, &["config", "user.email", "fixture@example.test"]);
    git(root, &["config", "user.name", "Fixture"]);
    fs::write(root.join("source.rb"), "puts 1\n").unwrap();
    fs::write(root.join(".understandignore"), "ignored/\n").unwrap();
    git(root, &["add", "."]); git(root, &["commit", "-qm", "baseline"]);
    fs::create_dir_all(root.join(".ua/intermediate")).unwrap();
    write_json(&root.join(".ua/knowledge-graph.json"), &json!({"nodes":[],"edges":[]})).unwrap();
    updates::write_meta(root, &ProcessGit.head(root).unwrap(), None).unwrap(); temp
}
#[test]
fn preflight_rejects_staged_unstaged_and_untracked_changes_even_when_head_matches() {
    for mode in ["staged", "unstaged", "untracked"] {
        let temp = setup(); let root = temp.path();
        let path = if mode == "untracked" { "new\nfile.rb" } else { "source.rb" };
        fs::write(root.join(path), "puts 2\n").unwrap();
        if mode == "staged" { git(root, &["add", path]); }
        let before = fs::read(root.join(".ua/meta.json")).unwrap();
        let result = updates::preflight(root, false).unwrap();
        assert_eq!(result["action"], "DIRTY_WORKTREE", "{mode}: {result}");
        assert_eq!(result["dirtyPaths"], json!([path]));
        assert_eq!(fs::read(root.join(".ua/meta.json")).unwrap(), before);
    }
}
#[test]
fn artifacts_and_ignored_files_are_allowed_but_scope_controls_are_relevant() {
    let temp = setup(); let root = temp.path();
    fs::create_dir_all(root.join("ignored")).unwrap();
    fs::write(root.join("ignored/a.rb"), "puts 1").unwrap();
    fs::write(root.join(".ua/generated.json"), "{}").unwrap();
    assert!(updates::relevant_worktree_changes(root, &ProcessGit).unwrap().is_empty());
    fs::write(root.join(".ua/.understandignore"), "other/\n").unwrap();
    fs::write(root.join("ignored/.gitignore"), "x\n").unwrap();
    assert_eq!(updates::relevant_worktree_changes(root, &ProcessGit).unwrap(), vec![".ua/.understandignore", "ignored/.gitignore"]);
}
#[test]
fn fingerprinting_preparation_and_finalization_reject_source_drift_without_publishing() {
    let temp = setup(); let root = temp.path();
    write_json(&root.join(".ua/intermediate/auto-update-state.json"), &json!({"currentCommit":ProcessGit.head(root)})).unwrap();
    let saved = fs::read(root.join(".ua/knowledge-graph.json")).unwrap();
    let metadata = fs::read(root.join(".ua/meta.json")).unwrap();
    fs::write(root.join("source.rb"), "puts 2").unwrap();
    for phase in [updates::fingerprint_check, updates::prepare_batches, updates::finalize] {
        assert!(phase(root).unwrap_err().to_string().contains("uncommitted"));
    }
    git(root, &["add", "source.rb"]); git(root, &["commit", "-qm", "advance"]);
    for phase in [updates::fingerprint_check, updates::prepare_batches, updates::finalize] {
        assert!(phase(root).unwrap_err().to_string().contains("HEAD changed"));
    }
    assert_eq!(fs::read(root.join(".ua/knowledge-graph.json")).unwrap(), saved);
    assert_eq!(fs::read(root.join(".ua/meta.json")).unwrap(), metadata);
}

#[test]
fn dirty_detection_is_scoped_to_subproject_and_checks_both_sides_of_renames() {
    let temp = setup(); let root = temp.path();
    fs::create_dir(root.join("sub")).unwrap();
    fs::write(root.join("sub/a.rb"), "puts 1").unwrap();
    git(root, &["add", "sub/a.rb"]); git(root, &["commit", "-qm", "subproject"]);
    fs::write(root.join("source.rb"), "puts 2").unwrap();
    assert!(updates::relevant_worktree_changes(&root.join("sub"), &ProcessGit).unwrap().is_empty());
    fs::write(root.join("sub/a.rb"), "puts 3").unwrap();
    assert_eq!(updates::relevant_worktree_changes(&root.join("sub"), &ProcessGit).unwrap(), vec!["a.rb"]);
    fs::create_dir(root.join("ignored")).unwrap();
    git(root, &["mv", "source.rb", "ignored/moved.rb"]);
    let changes = updates::relevant_worktree_changes(root, &ProcessGit).unwrap();
    assert!(changes.contains(&"source.rb".into()));
    assert!(!changes.contains(&"ignored/moved.rb".into()));
}
