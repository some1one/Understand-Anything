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

#[test]
#[ignore = "requires pinned Rust grammar; run with UA_TEST_PARSER_CACHE"]
fn rust_impl_owners_are_distinct_and_trait_owners_stay_unresolved() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") { parsers::configure(Some(std::path::Path::new(&cache))).unwrap(); }
    let source = "pub struct A; pub struct B; impl A { pub fn run(&self) {} } impl B { pub fn run(&self) {} } pub fn run() {}";
    let evidence = structure::analyze_file_strict("file.rs", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let owners: Vec<_> = evidence["structure"]["functions"].as_array().unwrap().iter().map(|f| f["owner"].clone()).collect();
    assert_eq!(owners, vec![json!("A"),json!("B"),json!("")]);
    let file = json!({"path":"file.rs","language":"rust","fileCategory":"code"});
    let result = structure::build_result(&file, 1, 1, Some(&evidence["structure"]), None, &json!({}));
    let seed = understand_anything::seed::build_seed(&json!({"batchIndex":0,"batchFiles":[file]}), &json!({"results":[result]}));
    for name in ["A.run","B.run","run"] {
        assert!(seed["nodes"].as_array().unwrap().iter().any(|n| n["id"] == format!("function:file.rs:{name}")), "{seed}");
    }
    let graph = |id: &str| json!({"nodes":[{"id":id,"name":"A.run","type":"function","filePath":"file.rs"}],"edges":[]});
    let comparison = understand_anything::incremental_symbols::compare_file_symbols("file.rs", &graph("function:file.rs:A.run"), &graph("func:file.rs:A.run"), &evidence, &evidence);
    assert_eq!(comparison["ok"], true, "{comparison}");
    let trait_source = "struct A; trait Job { fn run(&self); } impl Job for A { fn run(&self) {} }";
    let trait_evidence = structure::analyze_file_strict("file.rs", trait_source);
    assert_eq!(trait_evidence["status"], "succeeded", "{trait_evidence}");
    assert!(trait_evidence["structure"]["functions"][0]["owner"].is_null());
    assert_eq!(trait_evidence["declarationScopes"]["functions"][0]["scope"]["kind"], "unknown");
    let old = extract_file_fingerprint("file.rs", trait_source, Some(&trait_evidence["structure"]));
    let new = extract_file_fingerprint("file.rs", &format!("{trait_source}\n"), Some(&trait_evidence["structure"]));
    assert_eq!(compare_fingerprints(&old, &new).0, "STRUCTURAL");
}

#[test]
#[ignore = "requires pinned Rust grammar; run with UA_TEST_PARSER_CACHE"]
fn receiver_whitespace_changes_are_not_treated_as_proven_deletions() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") { parsers::configure(Some(std::path::Path::new(&cache))).unwrap(); }
    let before = structure::analyze_file_strict("file.rs", "struct Box<T>(T); impl<T> Box<T> { fn run(&self) {} } fn keep() {}");
    let after = structure::analyze_file_strict("file.rs", "struct Box<T>(T); impl<T> Box <T> { fn run(&self) {} } fn keep() {}");
    let old = json!({"nodes":[{"id":"function:file.rs:Box<T>.run","type":"function","name":"Box<T>.run","filePath":"file.rs"}],"edges":[]});
    let result = understand_anything::incremental_symbols::compare_file_symbols("file.rs", &old, &json!({"nodes":[],"edges":[]}), &before, &after);
    assert_eq!(result["ok"], false, "{result}");
    assert_eq!(result["missing"][0]["status"], "unknown", "{result}");
}

#[test]
#[ignore = "requires pinned C++ grammar; run with UA_TEST_PARSER_CACHE"]
fn cpp_inline_and_qualified_methods_preserve_receiver_identity() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") { parsers::configure(Some(std::path::Path::new(&cache))).unwrap(); }
    let source = "struct A { void run() {} }; void B::run() {} void run() {} void ns::C::run() {}";
    let evidence = structure::analyze_file_strict("file.cpp", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let owners: Vec<_> = evidence["structure"]["functions"].as_array().unwrap().iter().map(|f| f["owner"].clone()).collect();
    assert_eq!(owners, vec![json!("A"),json!("B"),json!(""),json!("ns::C")], "{evidence}");
    let scopes = evidence["declarationScopes"]["functions"].as_array().unwrap();
    assert_eq!(scopes.len(), 4, "{evidence}");
    for owner in ["A", "B", "ns::C"] {
        assert!(scopes.iter().any(|f| f["name"] == "run" && f["scope"]["name"] == owner), "{evidence}");
    }
    let file = json!({"path":"file.cpp","language":"cpp","fileCategory":"code"});
    let result = structure::build_result(&file, 1, 1, Some(&evidence["structure"]), None, &json!({}));
    let seed = understand_anything::seed::build_seed(&json!({"batchIndex":0,"batchFiles":[file]}), &json!({"results":[result]}));
    for name in ["A.run", "B.run", "run", "ns::C.run"] {
        assert!(seed["nodes"].as_array().unwrap().iter().any(|n| n["id"] == format!("function:file.cpp:{name}")), "{seed}");
    }
    for name in ["A.run", "B.run", "ns::C.run"] {
        let graph = |prefix: &str| json!({"nodes":[{"id":format!("{prefix}:file.cpp:{name}"),"name":name,"type":"function","filePath":"file.cpp"}],"edges":[]});
        let comparison = understand_anything::incremental_symbols::compare_file_symbols("file.cpp", &graph("function"), &graph("func"), &evidence, &evidence);
        assert_eq!(comparison["ok"], true, "{comparison}");
    }
    let special = structure::analyze_file_strict("file.cpp", "struct A { A() {} ~A() {} }; ");
    let names: Vec<_> = special["structure"]["functions"].as_array().unwrap().iter().map(|f| f["name"].clone()).collect();
    assert_eq!(names, vec![json!("A"), json!("~A")], "{special}");
}
