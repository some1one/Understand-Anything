use serde_json::{Value, json};
use std::{
    fs,
    path::Path,
    process::{Command, Output},
};
use understand_anything::{partition_layout as layout, persistence::write_json};

fn cli(root: &Path, command: &str, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg(command)
        .arg(root)
        .args(args)
        .output()
        .unwrap()
}
fn success(output: Output) -> String {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}
fn fixture(root: &Path) -> Value {
    fs::create_dir_all(root.join(".ua/intermediate")).unwrap();
    write_json(
        &root.join(".ua/intermediate/scan-result.json"),
        &json!({"files":[
        {"path":"src/auth/login.rs"}, {"path":"api/login.rs"},
        {"path":"src/auth/login.test.rs"}, {"path":"docs/auth.md"}, {"path":"other.rs"}
    ],"failures":[]}),
    )
    .unwrap();
    json!({"version":1,"mode":"custom","partitions":{
        "authentication":{"include":["/src/auth/**","/api/login.rs","/docs/auth.md"],"exclude":["**/*.test.rs"]},
        "api-contract":{"include":["/api/**"]},
        "future":{"include":["/future/**"]}
    }})
}
#[test]
fn regeneration_preserves_custom_rules_and_selects_every_overlapping_group() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let definition = fixture(root);
    let input = root.join("layout.json");
    write_json(&input, &definition).unwrap();
    success(cli(
        root,
        "write_partition_layout",
        &[input.to_str().unwrap()],
    ));
    success(cli(
        root,
        "write_config",
        &["--parts=authentication,api-contract,future"],
    ));
    for args in [vec![], vec!["--depth=3", "--source=somewhere"]] {
        success(cli(root, "partition_files", &args));
        let generated: Value = serde_json::from_slice(
            &fs::read(root.join(".ua/intermediate/partitions.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(
            generated["parts"]["authentication"],
            json!(["api/login.rs", "docs/auth.md", "src/auth/login.rs"])
        );
        assert_eq!(generated["parts"]["future"], json!([]));
        assert!(generated["parts"].get("src").is_none());
        assert_eq!(layout::load(root).unwrap(), definition);
    }
    write_json(&root.join("changes.json"), &json!(["api/login.rs"])).unwrap();
    assert_eq!(
        success(cli(
            root,
            "affected_parts",
            &[root.join("changes.json").to_str().unwrap()]
        )),
        "api-contract\nauthentication\n"
    );
    write_json(&root.join("changes.json"), &json!(["other.rs"])).unwrap();
    assert_eq!(
        success(cli(
            root,
            "affected_parts",
            &[root.join("changes.json").to_str().unwrap()]
        )),
        ""
    );
    assert_eq!(
        success(cli(root, "parts_to_process", &["--full"])),
        "authentication\napi-contract\nfuture\n"
    );
}
#[test]
fn hybrid_and_existing_legacy_maps_are_applied_without_rewriting_definitions() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let paths = vec![
        "docs/benchmarks/run.md".into(),
        "packages/web/scripts/test.sh".into(),
        "packages/web/src/app.ts".into(),
    ];
    let definition = json!({"splitDepth":2,"groupingOverrides":{"docs/benchmarks":"docs"},"pathPrefixParts":{"packages/web/scripts":"tooling"},"note":"keep me"});
    layout::save(root, &definition).unwrap();
    success(cli(root, "write_config", &["--parts=docs,tooling"]));
    let assigned = layout::assign(root, &paths, &[], Some(1)).unwrap();
    assert_eq!(assigned["docs"], vec!["docs/benchmarks/run.md"]);
    assert_eq!(assigned["tooling"], vec!["packages/web/scripts/test.sh"]);
    assert_eq!(layout::load(root).unwrap(), definition);
    let hybrid = json!({"mode":"hybrid","partitions":{"ui":{"include":["/packages/web/src/**"]}}});
    layout::save(root, &hybrid).unwrap();
    let assigned = layout::assign(root, &paths, &[], Some(1)).unwrap();
    assert_eq!(assigned["ui"], vec!["packages/web/src/app.ts"]);
    assert_eq!(assigned["packages"], vec!["packages/web/scripts/test.sh"]);
}
#[test]
fn layout_changes_invalidate_preparation_and_are_not_hidden_by_unchanged_git() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let definition = fixture(root);
    layout::save(root, &definition).unwrap();
    success(cli(
        root,
        "write_config",
        &["--parts=authentication,api-contract"],
    ));
    success(cli(root, "partition_files", &[]));
    write_json(
        &root.join(".ua/meta.json"),
        &json!({"partitionLayout":definition}),
    )
    .unwrap();
    assert!(!layout::changed(root).unwrap());
    layout::verify_inventory(root).unwrap();
    let mut revised = definition.clone();
    revised["partitions"]["authentication"]["exclude"] = json!(["/api/**"]);
    layout::save(root, &revised).unwrap();
    assert!(layout::changed(root).unwrap());
    assert!(layout::verify_inventory(root).is_err());
    assert!(
        understand_anything::partition_updates::verify_preparation(
            root,
            "authentication",
            &Value::Null
        )
        .is_err()
    );
    assert!(understand_anything::partition_updates::plan(root, "authentication", true).is_err());
    assert_eq!(
        understand_anything::partition::parts_to_process(root, false, &["other.rs".into()])
            .unwrap(),
        vec!["authentication", "api-contract"]
    );
    // Even regeneration during an in-flight analysis must not hide drift.
    success(cli(root, "partition_files", &[]));
    write_json(&root.join(".ua/intermediate/part-update.json"),&json!({"version":1,"part":"authentication","previousGraph":null,"partitionLayout":definition})).unwrap();
    assert!(
        understand_anything::partition_updates::verify_preparation(
            root,
            "authentication",
            &Value::Null
        )
        .unwrap_err()
        .to_string()
        .contains("layout changed")
    );
}
#[test]
fn invalid_definitions_and_unregistered_custom_graphs_leave_previous_state_intact() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let definition = fixture(root);
    layout::save(root, &definition).unwrap();
    for name in ["../escape", "a~b", "a,b", "/root", "a\\b"] {
        assert!(
            layout::save(
                root,
                &json!({"mode":"custom","partitions":{name:{"include":["**"]}}})
            )
            .is_err()
        );
        assert_eq!(layout::load(root).unwrap(), definition);
    }
    assert!(
        layout::save(
            root,
            &json!({"mode":"custom","partitions":{"x":{"include":["!src/**"]}}})
        )
        .is_err()
    );
    // Simulate an old hand-authored partition with no persistent definition.
    fs::rename(
        root.join(".ua/partition-layout.json"),
        root.join("layout.backup.json"),
    )
    .unwrap();
    fs::create_dir_all(root.join(".ua/partitions")).unwrap();
    let graph = json!({"part":"authentication","nodes":[{"id":"file:api/login.rs","type":"file","filePath":"api/login.rs"}],"edges":[]});
    let graph_path = root.join(".ua/partitions/authentication.knowledge-graph.json");
    write_json(&graph_path, &graph).unwrap();
    success(cli(
        root,
        "write_config",
        &["--depth=1", "--parts=authentication"],
    ));
    let output = cli(root, "partition_files", &[]);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("no definition"));
    assert_eq!(
        serde_json::from_slice::<Value>(&fs::read(graph_path).unwrap()).unwrap(),
        graph
    );
    assert!(!root.join(".ua/intermediate/partitions.json").exists());
}
