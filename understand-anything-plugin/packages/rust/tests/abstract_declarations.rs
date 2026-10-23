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

#[test]
#[ignore = "requires pinned Java and C# grammars; run with UA_TEST_PARSER_CACHE"]
fn java_enum_record_and_csharp_record_struct_keep_members_and_exports() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for (path, source, expected) in [
        ("Types.java", "public enum Mode { A, B; public void run() {} } public record Point(int x) { public int value() { return x; } }", vec![("Mode", "run"), ("Point", "value")]),
        ("Types.cs", "public record Point(int X) { public int Value() { return X; } } namespace Inner { public struct Counter { public int Get() { return 1; } } public record Label(string Name) { public string Read() { return Name; } } }", vec![("Point", "Value"), ("Counter", "Get"), ("Label", "Read")]),
    ] {
        let result = structure::analyze_file_strict(path, source);
        assert_eq!(result["status"], "succeeded", "{result}");
        let extracted = &result["structure"];
        let classes = extracted["classes"].as_array().unwrap();
        assert_eq!(classes.len(), expected.len(), "{result}");
        for (class, method) in expected {
            assert!(classes.iter().any(|c| c["name"] == class && c["methods"].as_array().unwrap().contains(&json!(method))), "{result}");
            assert!(extracted["functions"].as_array().unwrap().iter().any(|f| f["name"] == method), "{result}");
            assert!(extracted["exports"].as_array().unwrap().iter().any(|e| e["name"] == class), "{result}");
        }
    }
}
