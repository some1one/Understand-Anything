use serde_json::json;
use understand_anything::{
    incremental_symbols::compare_file_symbols, parsers, structure::analyze_file_strict,
};
#[test]
#[ignore = "requires pinned JS/TS grammars; run with UA_TEST_PARSER_CACHE"]
fn class_value_regions_resolve_direct_bindings_and_keep_indirect_values_uncertain() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for extension in ["js", "jsx", "ts", "tsx"] {
        let path = format!("file.{extension}");
        let before = analyze_file_strict(&path, "class A { run() {} keep() {} }");
        let old = json!({"nodes":[{"id":"old","type":"function","name":"A.run","filePath":path}],"edges":[]});
        for (source, expected) in [
            ("const A = class { run() {} keep() {} };", "still-present"),
            ("const A = (class { run() {} keep() {} });", "still-present"),
            ("A = class { run() {} keep() {} };", "still-present"),
            (
                "A = (class Internal { run() {} keep() {} });",
                "still-present",
            ),
            (
                "const B = class { keep() {} }; class A { keep() {} } Object.defineProperty(B.prototype,'run',descriptor);",
                "deleted",
            ),
            (
                "B = class { keep() {} }; class A { keep() {} } Object.defineProperty(B.prototype,'run',descriptor);",
                "deleted",
            ),
            (
                "const A = class { keep() {} }; Object.defineProperty(A.prototype,'run',descriptor);",
                "unknown",
            ),
            (
                "const B = class Internal { setup() { Object.defineProperty(Internal.prototype,'run',descriptor); } }; class A { keep() {} }",
                "deleted",
            ),
            ("const A = choose ? class { run() {} } : other;", "unknown"),
            ("A = factory(class { run() {} });", "unknown"),
            (
                "const A = {Nested: class { run() {} }}; function keep() {}",
                "deleted",
            ),
            (
                "class A { keep() {} static Nested = class { run() {} }; }",
                "deleted",
            ),
            (
                "function setup() { const A = class { run() {} }; } class A { keep() {} }",
                "deleted",
            ),
            (
                "function setup() { A = class { run() {} }; } let A;",
                "still-present",
            ),
        ] {
            let after = analyze_file_strict(&path, source);
            let result = compare_file_symbols(
                &path,
                &old,
                &json!({"nodes":[],"edges":[]}),
                &before,
                &after,
            );
            assert_eq!(
                result["missing"][0]["status"], expected,
                "{path}: {source}\n{result}\n{after}"
            );
        }
    }
}
