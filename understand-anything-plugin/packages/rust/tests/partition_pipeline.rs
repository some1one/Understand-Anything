use serde_json::{json, Value};
use std::{fs, process::Command};
use understand_anything::persistence::{read_json, write_json};
fn file(path: &str) -> Value {
    json!({"id":format!("file:{path}"),"type":"file","filePath":path,"name":path,"tags":[]})
}
#[test]
#[ignore = "requires pinned TypeScript grammar; run with UA_TEST_PARSER_CACHE"]
fn incremental_partition_preserves_unchanged_data_and_repairs_old_endpoint_ids() {
    run_partition_pipeline(false, false);
    run_partition_pipeline(true, false);
    run_partition_pipeline(true, true);
}
fn run_partition_pipeline(repair: bool, fail_repair: bool) {
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
    fs::write(root.join("src/caller.ts"), "export const caller = 1;\n").unwrap();
    fs::write(root.join("src/change.ts"), "export function run() {}\n").unwrap();
    git(&["add", "src"]);
    git(&["commit", "-qm", "base"]);
    let base = git(&["rev-parse", "HEAD"]);
    let inter = root.join(".ua/intermediate");
    fs::create_dir_all(inter.join("part-files")).unwrap();
    fs::create_dir(root.join(".ua/partitions")).unwrap();
    let old_id = "function:src/change.ts:legacyRun";
    let new_id = "function:src/change.ts:run";
    let previous = json!({"part":"src","project":{"gitCommitHash":base},"nodes":[file("src/caller.ts"),file("src/change.ts"),{"id":old_id,"type":"function","filePath":"src/change.ts","name":"run","tags":[]}],"edges":[{"source":"file:src/caller.ts","target":old_id,"type":"calls","weight":0.6,"direction":"forward"},{"source":"file:src/caller.ts","target":"file:src/change.ts","type":"imports","weight":0.8,"direction":"forward"}]});
    let saved = root.join(".ua/partitions/src.knowledge-graph.json");
    write_json(&saved, &previous).unwrap();
    let original = fs::read(&saved).unwrap();
    let source = "export function run() {}\nexport const changed = 2;\n";
    fs::write(root.join("src/change.ts"), source).unwrap();
    fs::write(root.join("src/new.ts"), "export const added = 1;\n").unwrap();
    git(&["add", "src"]);
    git(&["commit", "-qm", "change"]);
    let head = git(&["rev-parse", "HEAD"]);
    let paths = ["src/caller.ts", "src/change.ts", "src/new.ts"];
    write_json(&inter.join("part-files/src.json"), &json!(paths)).unwrap();
    write_json(&inter.join("scan-result.json"),&json!({"files":paths.iter().map(|p|json!({"path":p,"language":"typescript","fileCategory":"code"})).collect::<Vec<_>>(),"importMap":{"src/caller.ts":[],"src/change.ts":[],"src/new.ts":[]}})).unwrap();
    write_json(
        &inter.join("batch-999.json"),
        &json!({"nodes":[file("stale.ts")],"edges":[]}),
    )
    .unwrap();
    let run = |command: &str, extra: &[&str]| {
        let mut cmd = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"));
        if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
            cmd.args(["--parser-cache-dir", &cache]);
        }
        cmd.arg(command).arg(root).args(extra).output().unwrap()
    };
    let prepared = run("prepare_part_batches", &["src"]);
    assert!(
        prepared.status.success(),
        "{}",
        String::from_utf8_lossy(&prepared.stderr)
    );
    let summary: Value = serde_json::from_slice(&prepared.stdout).unwrap();
    assert_eq!(
        summary["filesToAnalyze"],
        json!(["src/change.ts", "src/new.ts"])
    );
    assert!(!inter.join("batch-999.json").exists());
    let batches = read_json(&inter.join("batches.json")).unwrap();
    for batch in batches["batches"].as_array().unwrap() {
        let mut nodes = vec![];
        let mut edges = vec![];
        for entry in batch["files"].as_array().unwrap() {
            let path = entry["path"].as_str().unwrap();
            assert_ne!(path, "src/caller.ts");
            nodes.push(file(path));
            if path == "src/change.ts" && !repair {
                nodes.push(
                    json!({"id":new_id,"type":"function","filePath":path,"name":"run","tags":[]}),
                );
            }
            if path == "src/new.ts" {
                edges.push(json!({"source":"file:src/new.ts","target":old_id,"type":"calls","weight":0.9,"direction":"forward"}));
            }
        }
        write_json(
            &inter.join(format!("batch-{}.json", batch["batchIndex"])),
            &json!({"nodes":nodes,"edges":edges}),
        )
        .unwrap();
    }
    let merged = run("merge_batch_graphs", &[]);
    assert!(
        merged.status.success(),
        "{}",
        String::from_utf8_lossy(&merged.stderr)
    );
    let candidates = read_json(&inter.join("part-edge-candidates.json")).unwrap();
    assert_eq!(candidates["edges"].as_array().unwrap().len(), 2);
    fs::write(root.join("src/change.ts"), "export function drift() {}\n").unwrap();
    assert!(!run("assemble_part_graph", &["src", &head]).status.success());
    assert_eq!(fs::read(&saved).unwrap(), original);
    assert!(inter.join("part-update.json").exists());
    assert!(!run("prepare_part_symbol_retry", &["src"]).status.success());
    fs::write(root.join("src/change.ts"), source).unwrap();
    if repair {
        assert!(!run("assemble_part_graph", &["src", &head]).status.success());
        let retry = run("prepare_part_symbol_retry", &["src"]);
        assert!(
            retry.status.success(),
            "{}",
            String::from_utf8_lossy(&retry.stderr)
        );
        let summary: Value = serde_json::from_slice(&retry.stdout).unwrap();
        assert_eq!(summary["filesToAnalyze"], json!(["src/change.ts"]));
        assert!(!run("prepare_part_symbol_retry", &["src"]).status.success());
        assert_eq!(fs::read(&saved).unwrap(), original);
        let batches = read_json(&inter.join("batches.json")).unwrap();
        for batch in batches["batches"].as_array().unwrap() {
            assert_eq!(batch["files"].as_array().unwrap().len(), 1);
            assert_eq!(batch["files"][0]["path"], "src/change.ts");
            write_json(&inter.join(format!("batch-{}.json",batch["batchIndex"])),&json!({"nodes":[file("src/change.ts"),{"id":new_id,"type":"function","filePath":"src/change.ts","name":"run","tags":[]}],"edges":[]})).unwrap();
        }
        if fail_repair {
            for batch in batches["batches"].as_array().unwrap() {
                write_json(
                    &inter.join(format!("batch-{}.json", batch["batchIndex"])),
                    &json!({"nodes":[file("src/change.ts")],"edges":[]}),
                )
                .unwrap();
            }
        }
        let merged = run("merge_batch_graphs", &[]);
        assert!(
            merged.status.success(),
            "{}",
            String::from_utf8_lossy(&merged.stderr)
        );
    }
    if fail_repair {
        assert!(!run("assemble_part_graph", &["src", &head]).status.success());
        assert!(!run("prepare_part_symbol_retry", &["src"]).status.success());
        assert_eq!(fs::read(&saved).unwrap(), original);
        assert!(run("prepare_part_batches", &["src"]).status.success());
        assert!(!run("prepare_part_symbol_retry", &["src"]).status.success());
        return;
    }
    if repair {
        let marker = inter.join("part-symbol-retry-src.json");
        let ready = read_json(&marker).unwrap();
        let mut incomplete = ready.clone();
        incomplete["status"] = json!("preparing");
        write_json(&marker, &incomplete).unwrap();
        assert!(!run("assemble_part_graph", &["src", &head]).status.success());
        assert_eq!(fs::read(&saved).unwrap(), original);
        write_json(&marker, &json!({"version":1})).unwrap();
        assert!(!run("assemble_part_graph", &["src", &head]).status.success());
        assert_eq!(fs::read(&saved).unwrap(), original);
        write_json(&marker, &ready).unwrap();
    }
    let published = run("assemble_part_graph", &["src", &head]);
    assert!(
        published.status.success(),
        "{}",
        String::from_utf8_lossy(&published.stderr)
    );
    let graph = read_json(&saved).unwrap();
    assert!(
        !graph["edges"]
            .as_array()
            .unwrap()
            .iter()
            .any(|e| e["type"] == "imports"),
        "Old imports must not be restored: {graph}"
    );
    for caller in ["src/caller.ts", "src/new.ts"] {
        assert!(
            graph["edges"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["source"] == format!("file:{caller}") && e["target"] == new_id),
            "{graph}"
        );
    }
    assert!(graph["nodes"]
        .as_array()
        .unwrap()
        .iter()
        .any(|n| n["id"] == "file:src/caller.ts" && n["stub"] != true));
    assert!(!inter.join("part-update.json").exists());
    assert!(!inter.join("part-symbol-retry-src.json").exists());
    assert!(!inter.join("batch-existing.json").exists());
}

#[test]
fn preparation_errors_preserve_scratch_and_new_parts_require_file_coverage() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    let inter = root.join(".ua/intermediate");
    fs::create_dir_all(inter.join("part-files")).unwrap();
    fs::write(root.join("README.md"), "# Project\n").unwrap();
    write_json(&inter.join("part-files/_root.json"), &json!(["README.md"])).unwrap();
    let scan = json!({"files":[{"path":"README.md","language":"markdown","fileCategory":"docs"}],"importMap":{"README.md":[]}});
    write_json(&inter.join("scan-result.json"), &scan).unwrap();
    let run = |command: &str, extra: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .arg(command)
            .arg(root)
            .args(extra)
            .output()
            .unwrap()
    };
    assert!(run("prepare_part_batches", &["_root"]).status.success());
    let before = fs::read(inter.join("part-update.json")).unwrap();
    write_json(
        &inter.join("scan-result.json"),
        &json!({"files":[],"failures":["unreadable"]}),
    )
    .unwrap();
    assert!(!run("prepare_part_batches", &["_root"]).status.success());
    assert_eq!(fs::read(inter.join("part-update.json")).unwrap(), before);
    write_json(&inter.join("scan-result.json"), &scan).unwrap();
    write_json(&inter.join("batch-0.json"), &json!({"nodes":[],"edges":[]})).unwrap();
    assert!(run("merge_batch_graphs", &[]).status.success());
    let missing = run("assemble_part_graph", &["_root"]);
    assert!(!missing.status.success());
    assert!(String::from_utf8_lossy(&missing.stderr).contains("README.md"));
    assert!(!root
        .join(".ua/partitions/_root.knowledge-graph.json")
        .exists());
    assert!(inter.join("part-update.json").exists());
    write_json(&inter.join("batch-0.json"),&json!({"nodes":[{"id":"document:README.md","type":"document","name":"README.md","filePath":"README.md","tags":[]}],"edges":[]})).unwrap();
    assert!(run("merge_batch_graphs", &[]).status.success());
    let saved = run("assemble_part_graph", &["_root"]);
    assert!(
        saved.status.success(),
        "{}",
        String::from_utf8_lossy(&saved.stderr)
    );
}
