use serde_json::json;
use understand_anything::imports::{ResolutionContext, resolve_import};
#[test]
fn scala_selectors_wildcards_and_package_objects_use_only_scanned_files() {
    let temp = tempfile::tempdir().unwrap();
    let paths = [
        "src/main/scala/com/example/A.scala",
        "scripts/com/example/B.sc",
        "src/main/scala/com/example/package.scala",
        "src/main/scala/com/example/nested/C.scala",
        "src/main/java/com/example/D.java",
        "src/main/scala/com/examples/Other.scala",
    ];
    let files: Vec<_> = paths.iter().map(|p| json!({"path":p})).collect();
    let mut context = ResolutionContext::new(temp.path(), &files);
    let importer = json!({"path":"src/Main.scala", "language":"scala"});
    for (source, specs, expected) in [
        ("com.example.A", vec!["A"], vec![paths[0]]),
        ("com.example", vec!["A", "B"], vec![paths[1], paths[0]]),
        ("com.example", vec!["A", "helper"], vec![paths[0], paths[2]]),
        ("com.example.helper", vec!["helper"], vec![paths[2]]),
        ("com.example", vec!["*"], vec![paths[1], paths[0], paths[2]]),
        ("external.Missing", vec!["Missing"], vec![]),
        ("com.example", vec![], vec![]),
    ] {
        let result = resolve_import(
            &json!({"source":source,"specifiers":specs}),
            &importer,
            &mut context,
        );
        assert_eq!(result, expected, "{source} {specs:?}");
    }
}
