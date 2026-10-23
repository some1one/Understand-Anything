//! Source/status cases captured from upstream's scoped symbol-evidence matrix.
use serde_json::{Value, json};
use understand_anything::{
    incremental_symbols::compare_file_symbols, parsers, structure::analyze_file_strict,
};
#[test]
#[ignore = "requires pinned language grammars; run with UA_TEST_PARSER_CACHE"]
fn upstream_scoped_symbol_evidence_source_matrix() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/upstream_symbol_matrix.json")).unwrap();
    let mut failures = vec![];
    for (index, case) in fixture["cases"].as_array().unwrap().iter().enumerate() {
        let path = format!("src/example.{}", case["extension"].as_str().unwrap());
        let mut old = json!({"id":format!("function:{path}:{}",case["name"].as_str().unwrap()),"type":"function","name":case["name"],"filePath":path});
        for (key, value) in case["oldExtra"].as_object().unwrap() {
            old[key] = value.clone();
        }
        let before = analyze_file_strict(&path, case["beforeSource"].as_str().unwrap());
        let after = analyze_file_strict(&path, case["currentSource"].as_str().unwrap());
        let result = compare_file_symbols(
            &path,
            &json!({"nodes":[old],"edges":[]}),
            &json!({"nodes":case["newNodes"],"edges":[]}),
            &before,
            &after,
        );
        let expected = case.get("rustExpected").unwrap_or(&case["expected"]);
        if result["missing"][0]["status"] != *expected {
            failures.push(format!(
                "case {index} {} expected {}: {}\nsource: {}",
                case["test"], expected, result, case["currentSource"]
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} mismatch(es):\n{}",
        failures.len(),
        failures.join("\n")
    );
}

#[test]
#[ignore = "requires pinned TypeScript and Ruby grammars; run with UA_TEST_PARSER_CACHE"]
fn retained_same_line_symbols_and_corrupt_scope_records_follow_the_native_contract() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for (path, source) in [
        ("file.ts", "function run() {} class A { run() {} }"),
        (
            "file.rb",
            "class A; def run; end; end; class B; def run; end; end",
        ),
    ] {
        let evidence = analyze_file_strict(path, source);
        let graph = json!({"nodes":[{"id":"old","type":"function","name":"A.run","filePath":path}],"edges":[]});
        assert_eq!(
            compare_file_symbols(path, &graph, &graph, &evidence, &evidence)["ok"],
            true
        );
    }
    let path = "file.ts";
    let before = analyze_file_strict(path, "function run() {} function keep() {}");
    let after = analyze_file_strict(path, "function keep() {}");
    let graph =
        json!({"nodes":[{"id":"old","type":"function","name":"run","filePath":path}],"edges":[]});
    let empty = json!({"nodes":[],"edges":[]});
    for (key, value) in [
        ("version", json!(0)),
        ("version", json!(2)),
        ("effects", json!([{}])),
        ("coverageGaps", json!([null])),
        ("coverageGaps", Value::Null),
    ] {
        let mut corrupt = after.clone();
        corrupt["declarationScopes"][key] = value;
        assert_eq!(
            compare_file_symbols(path, &graph, &empty, &before, &corrupt)["missing"][0]["status"],
            "unknown",
            "{key}"
        );
    }
    let mut absent = after.clone();
    absent.as_object_mut().unwrap().remove("declarationScopes");
    assert_eq!(
        compare_file_symbols(path, &graph, &empty, &before, &absent)["missing"][0]["status"],
        "unknown"
    );
}
