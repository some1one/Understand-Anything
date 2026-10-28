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

#[test]
fn explicit_partition_snapshot_does_not_inherit_merged_graph_freshness() {
    let tmp = setup();
    let root = tmp.path();
    let base = git(root, &["rev-parse", "HEAD"]);
    fs::write(root.join("sub/source.txt"), "new revision").unwrap();
    let next = commit(root);
    fs::create_dir_all(root.join(".ua/partitions")).unwrap();
    let part = root.join(".ua/partitions/sub.knowledge-graph.json");
    fs::write(&part, json!({"project":{"gitCommitHash":base,"analyzedAt":"old partition"},"nodes":[],"edges":[]}).to_string()).unwrap();
    fs::write(
        root.join(".ua/knowledge-graph.json"),
        json!({"project":{"gitCommitHash":next}}).to_string(),
    )
    .unwrap();
    for (path, status) in [(None, "fresh"), (Some(&part), "stale")] {
        let mut command = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"));
        command.arg("graph_freshness").arg(root);
        if let Some(path) = path {
            command.arg(path);
        }
        let output = command.output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(result["status"], status, "{result}");
        if path.is_some() {
            assert_eq!(result["lastAnalyzedAt"], "old partition");
        }
    }
}

#[test]
fn freshness_filters_committed_staged_unstaged_deleted_and_untracked_paths() {
    let tmp = setup();
    let root = tmp.path();
    fs::create_dir_all(root.join(".ua")).unwrap();
    fs::create_dir_all(root.join("excluded")).unwrap();
    fs::create_dir_all(root.join("node_modules")).unwrap();
    fs::write(root.join(".ua/.uaignore"), "excluded/\n").unwrap();
    // Root rules override the data-directory rules, including negation.
    fs::write(root.join(".uaignore"), "!excluded/keep.rs\n").unwrap();
    for path in ["excluded/committed.rs", "excluded/staged.rs", "excluded/unstaged.rs", "excluded/deleted.rs", "excluded/keep.rs", "node_modules/tracked.rs"] {
        fs::write(root.join(path), "baseline").unwrap();
    }
    let base = commit(root);
    fs::write(root.join("excluded/committed.rs"), "committed change").unwrap();
    commit(root);
    fs::write(root.join("excluded/staged.rs"), "staged change").unwrap();
    git(root, &["add", "excluded/staged.rs"]);
    fs::write(root.join("excluded/unstaged.rs"), "unstaged change").unwrap();
    fs::rename(root.join("excluded/deleted.rs"), root.join("excluded/renamed.rs")).unwrap();
    fs::write(root.join("excluded/untracked.rs"), "untracked change").unwrap();
    fs::write(root.join("node_modules/tracked.rs"), "default exclusion").unwrap();
    let clean = check(root, &base);
    assert_eq!(clean["status"], "fresh", "{clean}");
    assert_eq!(clean["changedFileCount"], 0);
    fs::write(root.join("excluded/keep.rs"), "included change").unwrap();
    let dirty = check(root, &base);
    assert_eq!(dirty["status"], "dirty");
    assert_eq!(dirty["changedFiles"], json!(["excluded/keep.rs"]));
    commit(root);
    let stale = check(root, &base);
    assert_eq!(stale["status"], "stale");
    assert_eq!(stale["changedFiles"], json!(["excluded/keep.rs"]));
}

#[test]
fn freshness_excludes_binary_changes_but_keeps_scripts_and_user_overrides() {
    let tmp = setup();
    let root = tmp.path();
    fs::create_dir(root.join("assets")).unwrap();
    for name in ["photo.PNG", "plugin.DLL", "library.so.3"] {
        fs::write(root.join("assets").join(name), [0, 255, 0]).unwrap();
    }
    let base = commit(root);
    fs::write(root.join("assets/photo.PNG"), [1, 255, 0]).unwrap();
    commit(root);
    fs::write(root.join("assets/plugin.DLL"), [1, 255, 0]).unwrap();
    git(root, &["add", "assets/plugin.DLL"]);
    fs::write(root.join("assets/library.so.3"), [1, 255, 0]).unwrap();
    fs::write(root.join("assets/new.OTF"), [1, 255, 0]).unwrap();
    let clean = check(root, &base);
    assert_eq!(clean["status"], "fresh", "{clean}");
    assert_eq!(clean["changedFileCount"], 0);
    fs::write(root.join("run.sh"), "#!/bin/sh\necho source\n").unwrap();
    assert_eq!(check(root, &base)["changedFiles"], json!(["run.sh"]));
    fs::create_dir(root.join(".ua")).unwrap();
    fs::write(root.join(".ua/.uaignore"), "!assets/photo.PNG\n").unwrap();
    let included = check(root, &base);
    assert_eq!(included["status"], "stale");
    assert_eq!(included["changedFiles"], json!(["assets/photo.PNG", "run.sh"]));
}
