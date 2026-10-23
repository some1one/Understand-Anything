use serde_json::json;
use understand_anything::{structure, parsers, incremental_symbols::compare_file_symbols};

#[test]
#[ignore = "requires pinned TypeScript and TSX grammars; run with UA_TEST_PARSER_CACHE"]
fn abstract_classes_and_methods_reach_structure_and_symbol_evidence() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for path in ["file.ts", "file.tsx"] {
        let source = "abstract class Local { abstract load(): void; concrete() {} } export abstract class Public { abstract run(): void; } export default abstract class Default { abstract start(): void; }";
        let evidence = structure::analyze_file_strict(path, source);
        assert_eq!(evidence["status"], "succeeded", "{evidence}");
        let classes = evidence["structure"]["classes"].as_array().unwrap();
        assert_eq!(classes.len(), 3);
        assert_eq!(classes[0]["methods"], json!(["load", "concrete"]));
        assert_eq!(classes[1]["methods"], json!(["run"]));
        assert_eq!(classes[2]["methods"], json!(["start"]));
        let exports = evidence["structure"]["exports"].as_array().unwrap();
        assert!(exports.iter().any(|e| e["name"] == "Public"));
        assert!(exports.iter().any(|e| e["name"] == "default" && e["isDefault"] == true), "{exports:?}");
        let graph = |prefix: &str| json!({"nodes":[{"id":format!("{prefix}:{path}:Public.run"),"type":"function","name":"Public.run","filePath":path}],"edges":[]});
        let result = compare_file_symbols(path, &graph("function"), &graph("func"), &evidence, &evidence);
        assert_eq!(result["ok"], true, "{result}");
        assert_eq!(result["replacements"].as_array().unwrap().len(), 1);
        let missing = compare_file_symbols(path, &graph("function"), &json!({"nodes":[],"edges":[]}), &evidence, &evidence);
        assert_eq!(missing["ok"], false, "{missing}");
    }
}
