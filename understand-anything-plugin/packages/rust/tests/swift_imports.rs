use serde_json::json;
use understand_anything::imports::{ResolutionContext, extract_import_map, resolve_import};
#[test]
fn swift_modules_resolve_conventions_custom_targets_and_nested_packages() {
    let temp = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(temp.path().join("nested")).unwrap();
    std::fs::write(temp.path().join("nested/Package.swift"), r#"
        // .target(name: "Ghost", path: "Custom")
        /* .target(name: "AlsoGhost", path: "Custom") */
        let package = Package(targets: [
            .target(name: "Engine", dependencies: [.product(name: "External", package: "ext")], path: "Custom"),
            .testTarget(name: "EngineTests"), .executableTarget(name: "Tool")
        ])
    "#).unwrap();
    let files = json!([
        {"path":"nested/Package.swift"}, {"path":"nested/Custom/A.swift"}, {"path":"nested/Custom/B.swift"},
        {"path":"nested/Tests/EngineTests/Test.swift"}, {"path":"nested/Sources/Tool/Main.swift"},
        {"path":"Sources/Models/Model.swift"}, {"path":"Frameworks/UI/View.swift"}, {"path":"App/Main.swift"}
    ]);
    let mut context = ResolutionContext::new(temp.path(), files.as_array().unwrap());
    let file = json!({"path":"nested/Custom/A.swift", "language":"swift"});
    for (module, expected) in [
        ("Engine", vec!["nested/Custom/B.swift"]),
        ("Engine.Widget", vec!["nested/Custom/B.swift"]),
        ("EngineTests", vec!["nested/Tests/EngineTests/Test.swift"]),
        ("Tool", vec!["nested/Sources/Tool/Main.swift"]),
        ("Models", vec!["Sources/Models/Model.swift"]),
        ("UI", vec!["Frameworks/UI/View.swift"]),
        ("App", vec!["App/Main.swift"]),
        ("Foundation", vec![]),
        ("Ghost", vec![]),
        ("AlsoGhost", vec![]),
    ] {
        assert_eq!(
            resolve_import(&json!({"source":module}), &file, &mut context),
            expected,
            "{module}"
        );
    }
}
#[test]
fn unreadable_swift_manifest_prevents_import_publication() {
    let temp = tempfile::tempdir().unwrap();
    let input = json!({"projectRoot":temp.path(), "files":[{"path":"Package.swift","fileCategory":"code","language":"swift"}]});
    let error = extract_import_map(&input).unwrap_err().to_string();
    assert!(
        error.contains("Package.swift") && error.contains("configuration read failed"),
        "{error}"
    );
}
