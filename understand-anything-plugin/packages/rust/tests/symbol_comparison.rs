use serde_json::{Value, json};
use understand_anything::{incremental_symbols::compare_file_symbols, parsers, structure::analyze_file_strict};
fn function(id: &str, name: &str) -> Value { json!({"id":id,"name":name,"type":"function","filePath":"file.ts"}) }
fn graph(nodes: Vec<Value>) -> Value { json!({"nodes":nodes,"edges":[]}) }
fn compare(old: &Value, new: &Value, before: &str, after: &str) -> Value {
    compare_file_symbols("file.ts", old, new, &analyze_file_strict("file.ts", before), &analyze_file_strict("file.ts", after))
}
#[test]
fn absent_parser_evidence_never_authorizes_symbol_deletion() {
    let old = graph(vec![function("function:file.ts:run", "run")]);
    let result = compare_file_symbols("file.ts", &old, &graph(vec![]), &json!({"status":"failed"}), &json!({"status":"unsupported"}));
    assert_eq!(result["ok"], false);
    assert_eq!(result["missing"][0]["status"], "unknown");
}
#[test]
#[ignore = "requires pinned TypeScript grammar; run with UA_TEST_PARSER_CACHE"]
fn comparisons_distinguish_loss_deletion_remapping_and_runtime_uncertainty() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") { parsers::configure(Some(std::path::Path::new(&cache))).unwrap(); }
    let old = graph(vec![function("function:file.ts:run", "run")]);
    let source = "function run() {} function keep() {}";
    let lost = compare(&old, &graph(vec![]), source, source);
    assert_eq!(lost["missing"][0]["status"], "still-present", "{lost}");
    let renamed = graph(vec![function("func:file.ts:run", "run")]);
    let result = compare(&old, &renamed, source, source);
    assert_eq!(result["ok"], true, "{result}");
    assert_eq!(result["replacements"], json!([{"oldId":"function:file.ts:run","newId":"func:file.ts:run"}]));
    let deleted = compare(&old, &graph(vec![]), source, "function keep() {}");
    assert_eq!(deleted["missing"][0]["status"], "deleted", "{deleted}");
    assert_eq!(deleted["ok"], true);
    let base = analyze_file_strict("file.ts", source);
    let mut corrupt = analyze_file_strict("file.ts", "function keep() {}");
    corrupt["declarationScopes"]["coverageGaps"] = json!([{"name":null}]);
    let rejected = compare_file_symbols("file.ts", &old, &graph(vec![]), &base, &corrupt);
    assert_eq!(rejected["ok"], false, "{rejected}");

    for after in ["", "function keep() {} const run = existing;", "function keep() {} eval(source);", "function keep( {", "function keep() {} Object.defineProperty(target, key, descriptor);"] {
        let result = compare(&old, &graph(vec![]), source, after);
        assert_eq!(result["ok"], false, "{after}: {result}");
        assert_eq!(result["missing"][0]["status"], "unknown", "{result}");
    }
    let reused = graph(vec![function("function:file.ts:run", "keep")]);
    let result = compare(&old, &reused, source, "function keep() {}");
    assert_eq!(result["ok"], false, "{result}");
}
#[test]
#[ignore = "requires pinned TypeScript grammar; run with UA_TEST_PARSER_CACHE"]
fn same_name_members_require_owner_and_unique_source_bindings() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") { parsers::configure(Some(std::path::Path::new(&cache))).unwrap(); }
    let old = graph(vec![function("function:file.ts:A.run", "A.run")]);
    let source = "class A { run() {} } class B { run() {} }";
    let result = compare(&old, &graph(vec![function("function:file.ts:B.run", "B.run")]), source, source);
    assert_eq!(result["ok"], false, "{result}");
    assert_eq!(result["missing"][0]["status"], "still-present");
    let result = compare(&old, &graph(vec![function("func:file.ts:A.run", "A.run")]), source, source);
    assert_eq!(result["ok"], true, "{result}");
    let ambiguous = "function run() {} function run() {} function keep() {}";
    let old = graph(vec![function("function:file.ts:run", "run")]);
    let result = compare(&old, &graph(vec![]), ambiguous, "function keep() {}");
    assert_eq!(result["ok"], false, "{result}");
}
