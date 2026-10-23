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
