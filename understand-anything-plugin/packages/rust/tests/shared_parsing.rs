use understand_anything::{parsers, structure};

#[test]
fn combined_extraction_preserves_noncode_and_unknown_contracts() {
    for (path, source) in [("README.md", "# Heading\nText"), ("file.unknown", "anything"), ("data.json", "{\"a\":1}")] {
        assert_eq!(structure::analyze_file_full(path, source),
            (structure::analyze_file(path, source), structure::extract_call_graph(path, source)));
    }
}

#[test]
#[ignore = "requires pinned grammars; run with UA_TEST_PARSER_CACHE"]
fn shared_trees_preserve_structure_calls_and_independent_file_state() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let cases = [
        ("file.ts", "export function work() { return helper(); }"),
        ("file.tsx", "export function View() { return <main>{helper()}</main>; }"),
        ("file.py", "def work():\n    return helper()\n"),
        ("file.go", "package p\nfunc work() { helper() }"),
        ("file.rs", "fn work() { helper(); }"),
        ("file.cpp", "void work() { helper(); }"),
        ("file.rb", "def work\n helper()\nend"),
    ];
    for _ in 0..3 {
        for (path, source) in cases {
            let combined = structure::analyze_file_full(path, source);
            assert_eq!(combined, (structure::analyze_file(path, source), structure::extract_call_graph(path, source)), "{path}");
            assert!(!combined.0.unwrap()["functions"].as_array().unwrap().is_empty(), "{path}");
            assert!(!combined.1.unwrap().is_empty(), "{path}");
            let empty = structure::analyze_file_full(path, "");
            assert!(empty.0.unwrap()["functions"].as_array().unwrap().is_empty(), "{path}");
            assert!(empty.1.unwrap().is_empty(), "{path}");
        }
    }
    // Trees must remain usable after their parser is reused and reconfigured.
    let first = parsers::parse("typescript", "function first() {}").unwrap();
    let second = parsers::parse("typescript", "class Second {}").unwrap();
    assert_eq!(first.root_node().named_child(0).unwrap().kind(), "function_declaration");
    assert_eq!(second.root_node().named_child(0).unwrap().kind(), "class_declaration");
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let third = parsers::parse("typescript", "const third = 1;").unwrap();
    assert_eq!(third.root_node().named_child(0).unwrap().kind(), "lexical_declaration");
    assert_eq!(first.root_node().named_child(0).unwrap().kind(), "function_declaration");
    std::thread::spawn(|| {
        let tree = parsers::parse("typescript", "function threaded() {}").unwrap();
        assert!(!tree.root_node().has_error());
    }).join().unwrap();
}
