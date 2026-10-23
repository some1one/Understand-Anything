use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
use understand_anything::freshness;
fn git(root: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{args:?}: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().into()
}
fn setup() -> tempfile::TempDir {
    let temp = tempfile::tempdir().unwrap();
    git(temp.path(), &["init", "-q"]);
    git(
        temp.path(),
        &["config", "user.email", "fixture@example.test"],
    );
    git(temp.path(), &["config", "user.name", "Fixture"]);
    fs::create_dir(temp.path().join("sub")).unwrap();
    fs::write(temp.path().join("sub/source.txt"), "baseline").unwrap();
    commit(temp.path());
    temp
}
fn commit(root: &Path) -> String {
    git(root, &["add", "."]);
    git(root, &["commit", "-qm", "fixture"]);
    git(root, &["rev-parse", "HEAD"])
}
fn check(root: &Path, hash: &str) -> Value {
    freshness::check(
        root,
        &json!({"graphCommitHash":hash,"lastAnalyzedAt":"saved"}),
    )
}
#[test]
fn freshness_distinguishes_clean_dirty_behind_ahead_and_diverged_without_writes() {
    let tmp = setup();
    let root = tmp.path();
    let base = git(root, &["rev-parse", "HEAD"]);
    assert_eq!(check(root, &base)["status"], "fresh");
    fs::write(root.join("sub/source.txt"), "unstaged").unwrap();
    assert_eq!(check(root, &base)["status"], "dirty");
    git(root, &["add", "sub/source.txt"]);
    assert_eq!(
        check(root, &base)["changedFiles"],
        json!(["sub/source.txt"])
    );
    let next = commit(root);
    let behind = check(root, &base);
    assert_eq!(behind["status"], "stale");
    assert_eq!(behind["relation"], "behind");
    assert_eq!(behind["commitsBehind"], 1);
    assert_eq!(behind["commitsAhead"], 0);
    git(root, &["checkout", "--detach", &base]);
    let ahead = check(root, &next);
    assert_eq!(ahead["relation"], "ahead");
    assert_eq!(ahead["commitsAhead"], 1);
    fs::write(root.join("sub/source.txt"), "other branch").unwrap();
    commit(root);
    let diverged = check(root, &next);
    assert_eq!(diverged["relation"], "diverged");
    assert_eq!(diverged["commitsAhead"], 1);
    assert_eq!(diverged["commitsBehind"], 1);
    assert_eq!(diverged["lastAnalyzedAt"], "saved");
    assert!(!root.join(".ua").exists());
}
#[test]
fn freshness_is_scoped_and_excludes_artifacts_but_preserves_unusual_paths() {
    let tmp = setup();
    let root = tmp.path();
    let base = git(root, &["rev-parse", "HEAD"]);
    fs::write(root.join("sibling.txt"), "new").unwrap();
    commit(root);
    let sub = root.join("sub");
    assert_eq!(check(&sub, &base)["status"], "fresh");
    for dir in [".ua", ".understand-anything"] {
        fs::create_dir(sub.join(dir)).unwrap();
        fs::write(sub.join(dir).join("graph.json"), "{}").unwrap();
    }
    assert_eq!(check(&sub, &base)["status"], "fresh");
    let path = "new\nfile.txt";
    fs::write(sub.join(path), "new").unwrap();
    let dirty = check(&sub, &base);
    assert_eq!(dirty["status"], "dirty");
    assert_eq!(dirty["changedFiles"], json!([path]));
    assert_eq!(dirty["commitsBehind"], 0);
}
#[test]
fn unknown_states_and_cli_use_graph_identity_not_a_newer_metadata_watermark() {
    let tmp = setup();
    let root = tmp.path();
    let base = git(root, &["rev-parse", "HEAD"]);
    assert_eq!(
        freshness::check(root, &json!({}))["reason"],
        "missing-graph-commit"
    );
    assert_eq!(
        check(root, "not-a-commit")["reason"],
        "graph-commit-unavailable"
    );
    let missing = tempfile::tempdir().unwrap();
    assert_eq!(
        check(missing.path(), &base)["reason"],
        "git-head-unavailable"
    );
    fs::write(root.join("sub/source.txt"), "changed").unwrap();
    let next = commit(root);
    fs::create_dir(root.join(".ua")).unwrap();
    fs::write(
        root.join(".ua/knowledge-graph.json"),
        json!({"project":{"gitCommitHash":base,"analyzedAt":"snapshot"}}).to_string(),
    )
    .unwrap();
    fs::write(
        root.join(".ua/meta.json"),
        json!({"gitCommitHash":next}).to_string(),
    )
    .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("graph_freshness")
        .arg(root)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["status"], "stale");
    assert_eq!(result["lastAnalyzedAt"], "snapshot");
    let batch = freshness::batch(
        root,
        &json!({"old":{"graphCommitHash":base},"current":{"graphCommitHash":next},"missing":{}}),
    );
    assert_eq!(batch["old"]["status"], "stale");
    assert_eq!(batch["current"]["status"], "fresh");
    assert_eq!(batch["missing"]["status"], "unknown");
}
