use understand_anything::{parsers, structure::analyze_file_strict};
#[test]
fn unknown_and_noncode_inputs_do_not_claim_structural_evidence() {
    for path in ["file.unknown", "README.md", "config.json"] {
        let result = analyze_file_strict(path, "anything");
        assert_eq!(result["status"], "unsupported");
        assert!(result["structure"].is_null());
    }
}
#[test]
#[ignore = "requires pinned grammars; run with UA_TEST_PARSER_CACHE"]
fn strict_evidence_distinguishes_empty_valid_sources_from_syntax_failures() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for (path, valid, invalid, leaf) in [
        ("file.py", "def hello():\n    return 1\n", "def hello(:\n", "hello"),
        ("file.ts", "export function hello() { return 1; }", "function hello( {", "hello"),
        ("file.tsx", "export const View = () => <main>Hello</main>;", "export const View = (", "View"),
    ] {
        let empty = analyze_file_strict(path, "");
        assert_eq!(empty["status"], "succeeded", "{empty}");
        let result = analyze_file_strict(path, valid);
        assert_eq!(result["status"], "succeeded", "{result}");
        assert!(result["leafTexts"].as_array().unwrap().iter().any(|text| text == leaf));
        let failed = analyze_file_strict(path, invalid);
        assert_eq!(failed["status"], "failed", "{failed}");
        assert!(failed["structure"].is_null());
        assert!(failed["leafTexts"].as_array().unwrap().is_empty());
    }
}
