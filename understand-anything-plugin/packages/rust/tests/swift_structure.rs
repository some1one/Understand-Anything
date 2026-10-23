use serde_json::json;
use understand_anything::{imports, parsers, structure};
fn configure() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
}
#[test]
#[ignore = "requires pinned Swift grammar; run with UA_TEST_PARSER_CACHE"]
fn swift_containers_members_visibility_and_calls_are_extracted() {
    configure();
    let source = r#"
import Foundation
import struct Models.Item
func add(_ a: Int, forKey b: Int) -> Int { helper(); return a + b }
private func hidden() {}
class Box {
    let id: Int
    var value: Int { compute() }
    init(value: Int) { setup() }
    deinit { cleanup() }
    func save() { self.flush(); Store.persist(); other.send() }
    private func secret() {}
    subscript(index: Int) -> Int { return index }
    struct Nested { var name: String }
}
struct Model { var count: Int }
enum Mode { case active, paused }
actor Worker { func work() { helper() } }
protocol Repository {
    associatedtype Item
    var item: Item { get }
    func load(_ key: String) -> Item
}
extension Box { func reset() { clear() } }
"#;
    let evidence = structure::analyze_file_strict("file.swift", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let a = &evidence["structure"];
    for name in [
        "Box",
        "Nested",
        "Model",
        "Mode",
        "Worker",
        "Repository",
        "extension Box",
    ] {
        assert!(
            a["classes"]
                .as_array()
                .unwrap()
                .iter()
                .any(|c| c["name"] == name),
            "{a}"
        );
    }
    let box_type = a["classes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["name"] == "Box")
        .unwrap();
    assert_eq!(box_type["properties"], json!(["id", "value"]), "{a}");
    for (name, properties, methods) in [
        ("Mode", json!(["active", "paused"]), json!([])),
        ("Repository", json!(["Item", "item"]), json!(["load"])),
        ("extension Box", json!([]), json!(["reset"])),
    ] {
        let c = a["classes"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == name)
            .unwrap();
        assert_eq!(c["properties"], properties, "{a}");
        assert_eq!(c["methods"], methods, "{a}");
    }
    let functions = a["functions"].as_array().unwrap();
    let add = functions.iter().find(|f| f["name"] == "add").unwrap();
    assert_eq!(add["params"], json!(["a", "b"]), "{a}");
    assert_eq!(add["returnType"], "Int");
    for name in [
        "Box.init",
        "Box.deinit",
        "save",
        "subscript",
        "load",
        "reset",
    ] {
        assert!(functions.iter().any(|f| f["name"] == name), "{a}");
    }
    let exports = a["exports"].as_array().unwrap();
    for name in ["hidden", "secret", "extension Box", "Box.deinit"] {
        assert!(!exports.iter().any(|e| e["name"] == name), "{a}");
    }
    let calls = structure::extract_call_graph("file.swift", source).unwrap();
    for (caller, callee) in [
        ("add", "helper"),
        ("Box.init", "setup"),
        ("Box.deinit", "cleanup"),
        ("value", "compute"),
        ("save", "flush"),
        ("save", "Store.persist"),
        ("save", "send"),
    ] {
        assert!(
            calls
                .iter()
                .any(|c| c["caller"] == caller && c["callee"] == callee),
            "{calls:?}"
        );
    }
    assert_eq!(
        structure::analyze_file_full("file.swift", source),
        (Some(a.clone()), Some(calls))
    );
}
#[test]
#[ignore = "requires pinned Swift grammar; run with UA_TEST_PARSER_CACHE"]
fn swift_import_extraction_resolves_project_modules_end_to_end() {
    configure();
    let temp = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(temp.path().join("Sources/App")).unwrap();
    std::fs::create_dir_all(temp.path().join("Sources/Models")).unwrap();
    std::fs::write(
        temp.path().join("Sources/App/Main.swift"),
        "import Foundation\n@testable import Models\nimport struct Models.Item\n",
    )
    .unwrap();
    std::fs::write(
        temp.path().join("Sources/Models/Item.swift"),
        "struct Item {}\n",
    )
    .unwrap();
    let files = json!([
        {"path":"Sources/App/Main.swift", "language":"swift", "fileCategory":"code"},
        {"path":"Sources/Models/Item.swift", "language":"swift", "fileCategory":"code"}
    ]);
    let result =
        imports::extract_import_map(&json!({"projectRoot":temp.path(),"files":files})).unwrap();
    assert_eq!(
        result["importMap"]["Sources/App/Main.swift"],
        json!(["Sources/Models/Item.swift"]),
        "{result}"
    );
}

#[test]
#[ignore = "requires pinned Swift grammar; run with UA_TEST_PARSER_CACHE"]
fn swift_property_patterns_and_visibility_do_not_leak_initializer_locals() {
    configure();
    let source = r#"
public struct Point {
    var x, y: Double
    @Published var count = 0
    public let value = { let local = 1; return local }()
}
private struct Hidden {
    struct Inner {}
    func secret() {}
}
protocol Seeded { init(seed: String) }
enum State { case idle; case failed(Error); case loaded(Item) }
func fetch<T>(_ type: T.Type) async throws -> T { fatalError() }
"#;
    let evidence = structure::analyze_file_strict("file.swift", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let a = &evidence["structure"];
    assert_eq!(
        a["classes"][0]["properties"],
        json!(["x", "y", "count", "value"]),
        "{a}"
    );
    let exports = a["exports"].as_array().unwrap();
    for name in ["local", "Hidden", "Inner", "secret"] {
        assert!(!exports.iter().any(|e| e["name"] == name), "{a}");
    }
    let functions = a["functions"].as_array().unwrap();
    assert_eq!(
        functions
            .iter()
            .find(|f| f["name"] == "Seeded.init")
            .unwrap()["params"],
        json!(["seed"])
    );
    let fetch = functions.iter().find(|f| f["name"] == "fetch").unwrap();
    assert_eq!(fetch["params"], json!(["type"]));
    assert_eq!(fetch["returnType"], "T");
    assert_eq!(
        a["classes"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == "State")
            .unwrap()["properties"],
        json!(["idle", "failed", "loaded"])
    );
}
