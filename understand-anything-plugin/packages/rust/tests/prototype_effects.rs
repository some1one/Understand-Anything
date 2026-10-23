use serde_json::json;
use understand_anything::{
    incremental_symbols::compare_file_symbols, parsers, structure::analyze_file_strict,
};

#[test]
#[ignore = "requires pinned JS/TS grammars; run with UA_TEST_PARSER_CACHE"]
fn prototype_replacements_record_exact_keys_without_claiming_unknown_keys_are_absent() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for extension in ["js", "jsx", "ts", "tsx"] {
        let path = format!("file.{extension}");
        let old = json!({"nodes":[{"id":"old","type":"function","name":"A.run","filePath":path}],"edges":[]});
        let new = json!({"nodes":[],"edges":[]});
        let before = analyze_file_strict(&path, "class A { run() {} keep() {} }");
        for (value, expected) in [
            ("{ other() {} }", "deleted"),
            ("{ 'other': function() {} }", "deleted"),
            ("{ ['other']: function() {} }", "deleted"),
            ("{ other }", "deleted"),
            ("{ /* comment */ other() {} }", "deleted"),
            ("{}", "deleted"),
            ("{ run() {} }", "unknown"),
            ("{ get run() { return callback; } }", "unknown"),
            ("{ set run(value) {} }", "unknown"),
            ("{ 'run': function() {} }", "unknown"),
            ("{ ['run']: function() {} }", "unknown"),
            ("{ run }", "unknown"),
            ("{ [key]: function() {} }", "unknown"),
            ("{ ...methods }", "unknown"),
            ("{ __proto__: methods }", "unknown"),
            ("{ ['__proto__']: methods }", "deleted"),
            ("methods", "unknown"),
        ] {
            let source = format!("class A {{ keep() {{}} }} A.prototype = {value};");
            let after = analyze_file_strict(&path, &source);
            let result = compare_file_symbols(&path, &old, &new, &before, &after);
            assert_eq!(
                result["missing"][0]["status"], expected,
                "{path}: {source}\n{result}\n{after}"
            );
        }
        let after = analyze_file_strict(
            &path,
            "class A { keep() {} } A.prototype ||= { other() {} };",
        );
        let result = compare_file_symbols(&path, &old, &new, &before, &after);
        assert_eq!(
            result["missing"][0]["status"], "unknown",
            "{path}: {result}"
        );
    }
}
