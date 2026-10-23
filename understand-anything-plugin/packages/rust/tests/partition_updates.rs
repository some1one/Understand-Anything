use serde_json::json;
use std::{fs, process::Command};
use understand_anything::{partition_updates::plan, persistence::write_json};
#[test]
fn planning_uses_each_parts_revision_and_preserves_unchanged_graph_evidence() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let git = |args: &[&str]| {
        let out = Command::new("git")
            .args(args)
            .current_dir(root)
            .output()
            .unwrap();
        assert!(out.status.success());
        String::from_utf8(out.stdout).unwrap().trim().to_owned()
    };
    git(&["init", "-q"]);
    git(&["config", "user.name", "Test"]);
    git(&["config", "user.email", "test@example.com"]);
    fs::create_dir(root.join("src")).unwrap();
    for path in ["changed.md", "keep.md", "removed.md"] {
        fs::write(root.join("src").join(path), "old").unwrap();
    }
    git(&["add", "src"]);
    git(&["commit", "-qm", "base"]);
    let base = git(&["rev-parse", "HEAD"]);
    let data = root.join(".ua");
    let inter = data.join("intermediate");
    fs::create_dir_all(inter.join("part-files")).unwrap();
    fs::create_dir(data.join("partitions")).unwrap();
    let graph = json!({"project":{"gitCommitHash":base},"nodes":[
        {"id":"keep","type":"document","filePath":"src/keep.md"},
        {"id":"changed","type":"document","filePath":"src/changed.md"},
        {"id":"removed","type":"document","filePath":"src/removed.md"},
        {"id":"stub","stub":true,"filePath":"src/new\nfile.md"}
    ],"edges":[{"source":"keep","target":"changed","type":"references"},{"source":"changed","target":"keep","type":"references"},{"source":"keep","target":"removed","type":"references"}]});
    let path = data.join("partitions/src.knowledge-graph.json");
    write_json(&path, &graph).unwrap();
    let saved = fs::read(&path).unwrap();
    fs::write(root.join("src/changed.md"), "new").unwrap();
    git(&["add", "src/changed.md"]);
    git(&["commit", "-qm", "changed"]);
    write_json(
        &data.join("meta.json"),
        &json!({"gitCommitHash":git(&["rev-parse","HEAD"])}),
    )
    .unwrap();
    fs::write(root.join("src/new\nfile.md"), "untracked").unwrap();
    let assigned = ["src/keep.md", "src/changed.md", "src/new\nfile.md"];
    write_json(&inter.join("part-files/src.json"), &json!(assigned)).unwrap();
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":assigned.iter().map(|p|json!({"path":p})).collect::<Vec<_>>()}),
    )
    .unwrap();
    let result = plan(root, "src", false).unwrap();
    assert_eq!(result["mode"], "incremental");
    assert_eq!(result["baseCommit"], base);
    assert_eq!(
        result["filesToAnalyze"],
        json!(["src/changed.md", "src/new\nfile.md"])
    );
    assert_eq!(result["removedFiles"], json!(["src/removed.md"]));
    assert_eq!(result["baseline"]["nodes"], json!([graph["nodes"][0]]));
    assert_eq!(result["baseline"]["edges"], json!([graph["edges"][0]]));
    assert_eq!(fs::read(&path).unwrap(), saved);
    let full = plan(root, "src", true).unwrap();
    assert_eq!(full["mode"], "full");
    assert_eq!(full["filesToAnalyze"].as_array().unwrap().len(), 3);
    assert_eq!(full["baseline"]["nodes"], json!([]));
    let mut invalid = graph;
    invalid["project"]["gitCommitHash"] = json!("missing");
    write_json(&path, &invalid).unwrap();
    assert_eq!(
        plan(root, "src", false).unwrap()["reason"],
        "unverifiable-baseline"
    );
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":[],"failures":["unreadable"]}),
    )
    .unwrap();
    assert!(plan(root, "src", false).is_err());
}

#[test]
fn subproject_plans_handle_dirty_files_and_new_or_empty_parts() {
    let temp = tempfile::tempdir().unwrap();
    let repo = temp.path();
    let root = repo.join("project");
    fs::create_dir(&root).unwrap();
    let git = |args: &[&str]| {
        let out = Command::new("git")
            .args(args)
            .current_dir(repo)
            .output()
            .unwrap();
        assert!(out.status.success());
        String::from_utf8(out.stdout).unwrap().trim().to_owned()
    };
    git(&["init", "-q"]);
    git(&["config", "user.name", "Test"]);
    git(&["config", "user.email", "test@example.com"]);
    fs::write(root.join("file.md"), "original").unwrap();
    fs::write(repo.join("outside.md"), "original").unwrap();
    git(&["add", "."]);
    git(&["commit", "-qm", "base"]);
    let base = git(&["rev-parse", "HEAD"]);
    let inter = root.join(".ua/intermediate");
    fs::create_dir_all(inter.join("part-files")).unwrap();
    fs::create_dir(root.join(".ua/partitions")).unwrap();
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":[{"path":"file.md"}]}),
    )
    .unwrap();
    write_json(&inter.join("part-files/_root.json"), &json!(["file.md"])).unwrap();
    let new = plan(&root, "_root", false).unwrap();
    assert_eq!(new["reason"], "new-part");
    assert_eq!(new["filesToAnalyze"], json!(["file.md"]));
    let graph = json!({"project":{"gitCommitHash":base},"nodes":[{"id":"file:file.md","type":"document","filePath":"file.md"}],"edges":[]});
    write_json(
        &root.join(".ua/partitions/_root.knowledge-graph.json"),
        &graph,
    )
    .unwrap();
    fs::write(repo.join("outside.md"), "changed outside").unwrap();
    assert_eq!(
        plan(&root, "_root", false).unwrap()["filesToAnalyze"],
        json!([])
    );
    fs::write(root.join("file.md"), "dirty local change").unwrap();
    assert_eq!(
        plan(&root, "_root", false).unwrap()["filesToAnalyze"],
        json!(["file.md"])
    );
    write_json(&inter.join("part-files/_root.json"), &json!([])).unwrap();
    let empty = plan(&root, "_root", false).unwrap();
    assert_eq!(empty["filesToAnalyze"], json!([]));
    assert_eq!(empty["removedFiles"], json!(["file.md"]));
    assert_eq!(empty["baseline"]["nodes"], json!([]));
    write_json(&inter.join("part-files/_root.json"), &json!(["missing.md"])).unwrap();
    assert!(plan(&root, "_root", false).is_err());
}

#[test]
fn selection_checks_saved_part_revisions_beyond_the_merged_changed_list() {
    use understand_anything::{partition::parts_to_process, persistence::save_config};
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let git = |args: &[&str]| {
        let output = Command::new("git")
            .args(args)
            .current_dir(root)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap().trim().to_owned()
    };
    git(&["init", "-q"]);
    git(&["config", "user.name", "Test"]);
    git(&["config", "user.email", "test@example.com"]);
    let parts = ["old", "ahead", "current", "other"];
    for part in parts {
        fs::create_dir(root.join(part)).unwrap();
        fs::write(root.join(part).join("file.md"), "base").unwrap();
    }
    git(&["add", "."]);
    git(&["commit", "-qm", "base"]);
    let base = git(&["rev-parse", "HEAD"]);
    fs::write(root.join("old/file.md"), "current").unwrap();
    git(&["add", "old"]);
    git(&["commit", "-qm", "current"]);
    let current = git(&["rev-parse", "HEAD"]);
    fs::write(root.join("ahead/file.md"), "future").unwrap();
    git(&["add", "ahead"]);
    git(&["commit", "-qm", "future partial analysis"]);
    let future = git(&["rev-parse", "HEAD"]);
    git(&["checkout", "-q", &current]);
    let data = root.join(".ua");
    let inter = data.join("intermediate");
    fs::create_dir_all(inter.join("part-files")).unwrap();
    fs::create_dir_all(data.join("partitions")).unwrap();
    save_config(root, &json!({"includedParts":parts,"splitDepth":1})).unwrap();
    write_json(&data.join("meta.json"), &json!({"gitCommitHash":current})).unwrap();
    let scan_files: Vec<_> = parts
        .iter()
        .map(|p| json!({"path":format!("{p}/file.md")}))
        .collect();
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":scan_files}),
    )
    .unwrap();
    for (part, hash) in [
        ("old", &base),
        ("ahead", &future),
        ("current", &current),
        ("other", &current),
    ] {
        let path = format!("{part}/file.md");
        write_json(
            &inter.join(format!("part-files/{part}.json")),
            &json!([path]),
        )
        .unwrap();
        write_json(&data.join(format!("partitions/{part}.knowledge-graph.json")),&json!({"project":{"gitCommitHash":hash},"nodes":[{"id":format!("file:{path}"),"type":"file","filePath":path}],"edges":[]})).unwrap();
    }
    let changed = vec!["other/file.md".to_owned()];
    assert_eq!(
        parts_to_process(root, false, &changed).unwrap(),
        vec!["ahead", "old", "other"]
    );
    // Scope removal needs refreshing even with no source change for that part.
    write_json(&inter.join("part-files/current.json"), &json!([])).unwrap();
    assert_eq!(
        parts_to_process(root, false, &changed).unwrap(),
        vec!["ahead", "current", "old", "other"]
    );
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":[],"failures":["unreadable"]}),
    )
    .unwrap();
    assert!(parts_to_process(root, false, &changed).is_err());
}
