use serde_json::json;
use understand_anything::{imports, parsers, scan, structure};
fn configure() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
}
#[test]
fn scala_sources_and_build_configuration_are_classified() {
    for p in ["Main.scala", "script.sc"] {
        assert_eq!(scan::detect_language(p), "scala");
        assert_eq!(scan::detect_category(p), "code");
        assert_eq!(
            parsers::detect_registry_language(p).as_deref(),
            Some("scala")
        );
    }
    assert_eq!(scan::detect_language("build.sbt"), "scala");
    assert_eq!(scan::detect_category("build.sbt"), "config");
}
#[test]
#[ignore = "requires pinned Scala grammar; run with UA_TEST_PARSER_CACHE"]
fn scala_types_members_extensions_visibility_and_calls_are_extracted() {
    configure();
    let source = r#"
package demo {
case class User(id: Long, name: String)
class Service(val repo: Repo, hidden: Int) {
  private val secret = 1
  def run(a: Int)(b: String): Int = { helper(a); repo.save[User](a); new User(a, b); a }
  class Nested {}
}
trait Repo { def save(value: User): Unit }
object Main { def start(): Unit = helper() }
private object Hidden { def secret(): Unit = helper() }
enum Color { case Red, Green }
extension (s: String)
  def shout: String = s.toUpperCase
}
"#;
    let evidence = structure::analyze_file_strict("file.scala", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let a = &evidence["structure"];
    let classes = a["classes"].as_array().unwrap();
    for name in [
        "User", "Service", "Nested", "Repo", "Main", "Hidden", "Color",
    ] {
        assert!(classes.iter().any(|c| c["name"] == name), "{a}");
    }
    assert_eq!(
        classes.iter().find(|c| c["name"] == "User").unwrap()["properties"],
        json!(["id", "name"])
    );
    assert_eq!(
        classes.iter().find(|c| c["name"] == "Service").unwrap()["properties"],
        json!(["repo", "secret"])
    );
    assert_eq!(
        classes.iter().find(|c| c["name"] == "Color").unwrap()["properties"],
        json!(["Red", "Green"])
    );
    let functions = a["functions"].as_array().unwrap();
    let run = functions.iter().find(|f| f["name"] == "run").unwrap();
    assert_eq!(run["params"], json!(["a", "b"]));
    assert_eq!(run["returnType"], "Int");
    assert!(functions.iter().any(|f| f["name"] == "shout"));
    assert!(
        !a["exports"]
            .as_array()
            .unwrap()
            .iter()
            .any(|e| e["name"] == "secret" || e["name"] == "Hidden")
    );
    let calls = structure::extract_call_graph("file.scala", source).unwrap();
    for callee in ["helper", "save", "User"] {
        assert!(
            calls
                .iter()
                .any(|c| c["caller"] == "run" && c["callee"] == callee),
            "{calls:?}"
        );
    }
    assert_eq!(
        structure::analyze_file_full("file.scala", source),
        (Some(a.clone()), Some(calls))
    );
}
#[test]
#[ignore = "requires pinned Scala grammar; run with UA_TEST_PARSER_CACHE"]
fn scala_selector_imports_resolve_original_names_and_exclude_hidden_selectors() {
    configure();
    let temp = tempfile::tempdir().unwrap();
    std::fs::create_dir_all(temp.path().join("com/example")).unwrap();
    let source = "import com.example.{A => Renamed, B => _}\nimport com.example.helper\nimport com.example.{B => _}\n";
    std::fs::write(temp.path().join("Main.scala"), source).unwrap();
    for p in ["A.scala", "B.sc", "package.scala"] {
        std::fs::write(temp.path().join("com/example").join(p), "").unwrap();
    }
    let imports = structure::try_extract_import_sources("scala", source).unwrap();
    assert_eq!(imports[0]["specifiers"], json!(["A"]));
    assert_eq!(imports[2]["specifiers"], json!([]));
    let paths = [
        "Main.scala",
        "com/example/A.scala",
        "com/example/B.sc",
        "com/example/package.scala",
    ];
    let files: Vec<_> = paths
        .iter()
        .map(|p| json!({"path":p,"language":"scala","fileCategory":"code"}))
        .collect();
    let result =
        imports::extract_import_map(&json!({"projectRoot":temp.path(),"files":files})).unwrap();
    assert_eq!(
        result["importMap"]["Main.scala"],
        json!(["com/example/A.scala", "com/example/package.scala"]),
        "{result}"
    );
}

#[test]
#[ignore = "requires pinned Scala grammar; run with UA_TEST_PARSER_CACHE"]
fn scala_package_objects_exports_and_infix_calls_keep_their_names() {
    configure();
    let source = r#"
package object util { val answer = 42; def help(): Int = answer }
export service.{save as persist}
given intOrder: Ordering[Int] = Ordering.Int
def applyAll(items: List[Int]): List[Int] = items map transform
import com.example.A, com.example.B
import com.example._
"#;
    let evidence = structure::analyze_file_strict("file.sc", source);
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let a = &evidence["structure"];
    assert!(
        a["classes"]
            .as_array()
            .unwrap()
            .iter()
            .any(|c| c["name"] == "util")
    );
    for name in ["persist", "intOrder", "answer"] {
        assert!(
            a["exports"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["name"] == name),
            "{a}"
        );
    }
    let imports = a["imports"].as_array().unwrap();
    assert_eq!(imports.len(), 3, "{a}");
    assert_eq!(imports[0]["source"], "com.example.A");
    assert_eq!(imports[1]["source"], "com.example.B");
    assert_eq!(imports[2]["specifiers"], json!(["*"]));
    let calls = structure::extract_call_graph("file.sc", source).unwrap();
    assert!(
        calls
            .iter()
            .any(|c| c["caller"] == "applyAll" && c["callee"] == "map"),
        "{calls:?}"
    );
}
