use serde_json::json;
use understand_anything::{fingerprints::{compare_fingerprints, extract_file_fingerprint}, parsers, structure};
#[test]
fn receiver_changes_and_unresolved_receivers_require_structural_reanalysis() {
    let analysis = |owner| json!({"functions":[{"name":"Run","owner":owner,"params":[],"lineRange":[1,1]}]});
    let a = extract_file_fingerprint("file.go", "a", Some(&analysis(json!("A"))));
    let b = extract_file_fingerprint("file.go", "b", Some(&analysis(json!("B"))));
    assert_eq!(compare_fingerprints(&a, &b).0, "STRUCTURAL");
    let free = extract_file_fingerprint("file.go", "free", Some(&analysis(json!(""))));
    assert_eq!(compare_fingerprints(&a, &free).0, "STRUCTURAL");
    let unknown = extract_file_fingerprint("file.go", "unknown", Some(&analysis(json!(null))));
    let changed = extract_file_fingerprint("file.go", "changed", Some(&analysis(json!(null))));
    assert_eq!(compare_fingerprints(&unknown, &changed).0, "STRUCTURAL");
    assert_eq!(compare_fingerprints(&unknown, &unknown).0, "NONE");
}
#[test]
#[ignore = "requires pinned Go grammar; run with UA_TEST_PARSER_CACHE"]
fn go_receivers_survive_extraction_seeding_and_symbol_comparison() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") { parsers::configure(Some(std::path::Path::new(&cache))).unwrap(); }
    let source = "package p\ntype A[T any] struct {}\ntype B struct {}\nfunc (a *A[B]) Run() {}\nfunc (b B) Run() {}\nfunc Run() {}\n";
    let evidence = structure::analyze_file_strict("file.go", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let owners: Vec<_> = evidence["structure"]["functions"].as_array().unwrap().iter().map(|f| f["owner"].clone()).collect();
    assert_eq!(owners, vec![json!("A"),json!("B"),json!("")]);
    let scopes = evidence["declarationScopes"]["functions"].as_array().unwrap();
    assert!(scopes.iter().any(|f| f["name"] == "Run" && f["scope"]["name"] == "A"));
    let file = json!({"path":"file.go","language":"go","fileCategory":"code"});
    let result = structure::build_result(&file, 7, 7, Some(&evidence["structure"]), None, &json!({}));
    let graph = understand_anything::seed::build_seed(&json!({"batchIndex":0,"batchFiles":[file]}), &json!({"results":[result]}));
    for name in ["A.Run","B.Run","Run"] {
        assert!(graph["nodes"].as_array().unwrap().iter().any(|n| n["id"] == format!("function:file.go:{name}")), "{graph}");
    }
    let graph = |id: &str| json!({"nodes":[{"id":id,"name":"A.Run","type":"function","filePath":"file.go"}],"edges":[]});
    let comparison = understand_anything::incremental_symbols::compare_file_symbols("file.go", &graph("function:file.go:A.Run"), &graph("func:file.go:A.Run"), &evidence, &evidence);
    assert_eq!(comparison["ok"], true, "{comparison}");
    assert_eq!(comparison["replacements"].as_array().unwrap().len(), 1);
}
