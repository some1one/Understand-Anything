use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};
use ua::persistence::{read_json, write_json};
use understand_anything as ua;

fn run(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args(args)
        .output()
        .unwrap()
}
fn ok(args: &[&str]) {
    let result = run(args);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
}
fn git(root: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .args(args)
        .current_dir(root)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}
fn init(root: &Path) {
    // These regressions exercise compatibility with existing legacy projects.
    fs::create_dir_all(root.join(".understand-anything")).unwrap();
    git(root, &["init", "-q"]);
    git(root, &["config", "user.email", "fixture@example.test"]);
    git(root, &["config", "user.name", "Fixture"]);
    fs::write(
        root.join(".gitignore"),
        ".understand-anything/*\n!.understand-anything/.uaignore\n",
    )
    .unwrap();
}
fn commit(root: &Path) -> String {
    git(root, &["add", "."]);
    git(root, &["commit", "-qm", "fixture"]);
    git(root, &["rev-parse", "HEAD"])
}
fn node(path: &str) -> Value {
    json!({"id":format!("file:{path}"),"filePath":path,"type":"file","name":path,
           "summary":"fixture","tags":[],"complexity":"simple"})
}
fn refresh(root: &Path, changed: &[String]) -> Value {
    let dir = root.join(".understand-anything/intermediate");
    fs::create_dir_all(&dir).unwrap();
    let scan = ua::scan::scan_project(root).unwrap();
    write_json(&dir.join("scan-result.json"), &scan).unwrap();
    ok(&["partition_files", root.to_str().unwrap(), "--depth=1"]);
    for part in ua::partition::parts_to_process(root, false, changed).unwrap() {
        let inventory = read_json(&dir.join("partitions.json")).unwrap();
        let paths = ua::strings(&inventory["parts"][&part]);
        // Stand in for extraction, exercising actual fragment merge and persistence.
        ua::batch_files::replace(
            &dir,
            0,
            &[json!({"nodes":paths.iter().map(|p|node(p)).collect::<Vec<_>>(),"edges":[]})],
        )
        .unwrap();
        ua::batch_merge::merge_batch_directory(root).unwrap();
        ok(&["assemble_part_graph", root.to_str().unwrap(), &part]);
    }
    let graphs: Vec<_> = ["a", "b"]
        .iter()
        .map(|p| {
            read_json(
                &root
                    .join(".understand-anything/partitions")
                    .join(ua::partition::part_to_filename(p)),
            )
            .unwrap()
        })
        .collect();
    ua::merge::merge_graphs(&graphs).0
}

#[test]
fn committed_rename_refreshes_both_parts_and_legacy_prunes_old_path() {
    use ua::updates::GitClient;
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    init(root);
    fs::create_dir(root.join("a")).unwrap();
    fs::create_dir(root.join("b")).unwrap();
    let old = "a/ 文\nfile.py";
    let new = "b/ 文\nfile.py";
    fs::write(root.join(old), "x = 1\n").unwrap();
    let before = commit(root);
    ua::persistence::save_config(root, &json!({"splitDepth":1,"includedParts":["a","b"]})).unwrap();
    refresh(root, &[]);
    git(root, &["mv", old, new]);
    let after = commit(root);
    assert!(git(root, &["diff", "--name-status", &before, &after]).starts_with("R100"));
    let changed = ua::updates::ProcessGit
        .changed_files(root, &before, &after)
        .unwrap();
    assert_eq!(changed, vec![old, new]);
    assert_eq!(ua::staleness::get_changed_files(root, &before), changed);
    assert_eq!(
        ua::partition::parts_to_process(root, false, &changed).unwrap(),
        vec!["a", "b"]
    );
    let graph = refresh(root, &changed);
    assert_eq!(
        ua::updates::graph_file_paths(&graph),
        [new.to_owned()].into()
    );
    let empty =
        read_json(&root.join(".understand-anything/partitions/a.knowledge-graph.json")).unwrap();
    assert!(ua::array(&empty, "nodes").is_empty());
    let inter = root.join(".understand-anything/intermediate");
    write_json(&root.join(".understand-anything/knowledge-graph.json"), &json!({"nodes":[node(old),node("keep.py")],"edges":[{"source":format!("file:{old}"),"target":"file:keep.py","type":"imports","weight":1}]})).unwrap();
    write_json(
        &inter.join("change-analysis.json"),
        &json!({"filesToReanalyze":[new],"deletedFiles":[old]}),
    )
    .unwrap();
    ua::batch_files::replace(&inter, 0, &[json!({"nodes":[node(new)],"edges":[]})]).unwrap();
    let legacy = ua::updates::apply_batches(root).unwrap();
    assert!(!ua::updates::graph_file_paths(&legacy).contains(old));
    assert!(ua::updates::graph_file_paths(&legacy).contains(new));
    assert!(ua::array(&legacy, "edges").is_empty());
}

#[test]
fn ignore_only_commits_refresh_selected_parts_including_empty_and_restore_files() {
    for location in [
        ".uaignore",
        ".understand-anything/.uaignore",
    ] {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path();
        init(root);
        fs::create_dir(root.join("a")).unwrap();
        fs::create_dir(root.join("b")).unwrap();
        fs::write(root.join("a/f.py"), "x = 1\n").unwrap();
        fs::write(root.join("b/f.py"), "x = 2\n").unwrap();
        let mut previous = commit(root);
        ua::persistence::save_config(root, &json!({"splitDepth":1,"includedParts":["a","b"]}))
            .unwrap();
        refresh(root, &[]);
        for (rules, expected) in [
            (Some("a/\n"), 1),
            (Some("a/\nb/\n"), 0),
            (Some(""), 2),
            (None, 2),
        ] {
            match rules {
                Some(text) => fs::write(root.join(location), text).unwrap(),
                None => fs::remove_file(root.join(location)).unwrap(),
            }
            let current = commit(root);
            let changed = ua::staleness::get_changed_files(root, &previous);
            assert_eq!(changed, vec![location]);
            assert_eq!(
                ua::partition::parts_to_process(root, false, &changed).unwrap(),
                vec!["a", "b"]
            );
            let graph = refresh(root, &changed);
            assert_eq!(ua::array(&graph, "nodes").len(), expected);
            assert!(ua::array(&graph, "edges").is_empty());
            previous = current;
        }
    }
}

#[test]
fn legacy_ignore_updates_prune_and_restore_before_advancing_baseline() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    init(root);
    fs::create_dir(root.join("a")).unwrap();
    fs::write(root.join("a/f.rb"), "x = 1\n").unwrap();
    let before = commit(root);
    let ua_dir = root.join(".understand-anything");
    let inter = ua_dir.join("intermediate");
    fs::create_dir_all(&inter).unwrap();
    write_json(
        &ua_dir.join("knowledge-graph.json"),
        &json!({"nodes":[node("a/f.rb")],"edges":[],"layers":[]}),
    )
    .unwrap();
    ua::updates::write_meta(root, &before, None).unwrap();
    fs::write(root.join(".uaignore"), "a/\n").unwrap();
    let ignored = commit(root);
    let state = ua::updates::preflight(root, false).unwrap();
    assert_eq!(state["action"], "PROCEED");
    assert_eq!(
        read_json(&ua_dir.join("meta.json")).unwrap()["gitCommitHash"],
        before
    );
    write_json(&inter.join("auto-update-state.json"), &state).unwrap();
    let analysis = ua::updates::fingerprint_check(root).unwrap();
    assert_eq!(analysis["deletedFiles"], json!(["a/f.rb"]));
    write_json(&inter.join("change-analysis.json"), &analysis).unwrap();
    ua::updates::prepare_batches(root).unwrap();
    ua::updates::apply_batches(root).unwrap();
    ua::updates::finalize(root).unwrap();
    assert!(
        ua::array(
            &read_json(&ua_dir.join("knowledge-graph.json")).unwrap(),
            "nodes"
        )
        .is_empty()
    );
    assert_eq!(
        read_json(&ua_dir.join("meta.json")).unwrap()["gitCommitHash"],
        ignored
    );
    // Restoration must be classified as new even if an older fingerprint remains.
    fs::write(root.join(".uaignore"), "").unwrap();
    commit(root);
    let state = ua::updates::preflight(root, false).unwrap();
    write_json(&inter.join("auto-update-state.json"), &state).unwrap();
    let analysis = ua::updates::fingerprint_check(root).unwrap();
    assert_eq!(analysis["newFiles"], json!(["a/f.rb"]));
    write_json(&inter.join("change-analysis.json"), &analysis).unwrap();
    ua::updates::prepare_batches(root).unwrap();
    ua::batch_files::replace(&inter, 0, &[json!({"nodes":[node("a/f.rb")],"edges":[]})]).unwrap();
    ua::updates::apply_batches(root).unwrap();
    // Persistence failure must not advance the baseline.
    fs::rename(
        ua_dir.join("knowledge-graph.json"),
        ua_dir.join("saved-graph.json"),
    )
    .unwrap();
    fs::create_dir(ua_dir.join("knowledge-graph.json")).unwrap();
    assert!(ua::updates::finalize(root).is_err());
    assert_eq!(
        read_json(&ua_dir.join("meta.json")).unwrap()["gitCommitHash"],
        ignored
    );
    fs::remove_dir(ua_dir.join("knowledge-graph.json")).unwrap();
    fs::rename(
        ua_dir.join("saved-graph.json"),
        ua_dir.join("knowledge-graph.json"),
    )
    .unwrap();
    ua::updates::finalize(root).unwrap();
    assert_eq!(
        ua::updates::graph_file_paths(&read_json(&ua_dir.join("knowledge-graph.json")).unwrap()),
        ["a/f.rb".into()].into()
    );
    assert_eq!(
        read_json(&ua_dir.join("meta.json")).unwrap()["gitCommitHash"],
        state["currentCommit"]
    );
    assert!(read_json(&ua_dir.join("fingerprints.json")).unwrap()["files"]["a/f.rb"].is_object());
}

#[test]
fn finalization_retries_replace_exact_batch_and_invalid_drafts_preserve_it() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let inter = root.join(".understand-anything/intermediate");
    fs::create_dir_all(&inter).unwrap();
    write_json(&root.join("seed.json"), &json!({"nodes":[],"edges":[]})).unwrap();
    ua::batch_files::replace(&inter, 10, &[json!({"nodes":[],"edges":[]})]).unwrap();
    let neighbor = fs::read(inter.join("batch-10.json")).unwrap();
    for count in [61, 1, 121, 61, 61, 1] {
        let paths: Vec<_> = (0..count).map(|i| format!("f{i}.txt")).collect();
        let nodes: Vec<_> = paths.iter().map(|p| node(p)).collect();
        let edges = if count > 1 {
            vec![json!({"source":"file:f0.txt","target":"file:f1.txt","type":"calls","weight":1})]
        } else {
            vec![]
        };
        write_json(&root.join("context.json"), &json!({"batchIndex":1,"batchFiles":paths.iter().map(|p|json!({"path":p})).collect::<Vec<_>>()})).unwrap();
        write_json(
            &root.join("draft.json"),
            &json!({"nodes":nodes,"edges":edges}),
        )
        .unwrap();
        ok(&[
            "finalize_file_batch_output",
            root.to_str().unwrap(),
            root.join("context.json").to_str().unwrap(),
            root.join("seed.json").to_str().unwrap(),
            root.join("draft.json").to_str().unwrap(),
        ]);
        let merged = ua::batch_merge::merge_batch_directory(root).unwrap();
        assert_eq!(ua::array(&merged, "nodes").len(), count);
        assert_eq!(
            ua::array(&merged, "edges").len(),
            if count > 1 { 1 } else { 0 }
        );
        assert_eq!(fs::read(inter.join("batch-10.json")).unwrap(), neighbor);
    }
    let before = fs::read(inter.join("batch-1.json")).unwrap();
    write_json(&root.join("draft.json"), &json!({"nodes":[{}],"edges":[]})).unwrap();
    assert!(
        !run(&[
            "finalize_file_batch_output",
            root.to_str().unwrap(),
            root.join("context.json").to_str().unwrap(),
            root.join("seed.json").to_str().unwrap(),
            root.join("draft.json").to_str().unwrap()
        ])
        .status
        .success()
    );
    assert_eq!(fs::read(inter.join("batch-1.json")).unwrap(), before);
}
