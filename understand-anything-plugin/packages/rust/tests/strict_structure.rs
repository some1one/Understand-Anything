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

#[test]
#[ignore = "requires pinned grammars; run with UA_TEST_PARSER_CACHE"]
fn lexical_scopes_separate_same_name_methods_free_functions_and_locals() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for (path, source) in [
        ("file.ts", "class Worker { run() { function run() {} } } function run() {}"),
        ("file.py", "class Worker:\n    def run(self):\n        def run(): pass\ndef run(): pass\n"),
    ] {
        let evidence = analyze_file_strict(path, source);
        assert_eq!(evidence["status"], "succeeded", "{evidence}");
        let functions = evidence["declarationScopes"]["functions"].as_array().unwrap();
        let runs: Vec<_> = functions.iter().filter(|f| f["name"] == "run").collect();
        assert_eq!(runs.len(), 3, "{evidence}");
        assert!(runs.iter().any(|f| f["scope"]["kind"] == "file"));
        assert!(runs.iter().any(|f| f["scope"]["kind"] == "local"));
        assert!(runs.iter().any(|f| f["scope"]["kind"] == "class" && f["scope"]["name"] == "Worker"));
    }
}

#[test]
#[ignore = "requires pinned grammars; run with UA_TEST_PARSER_CACHE"]
fn expression_bindings_and_nested_types_do_not_claim_wrong_public_owners() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let evidence = analyze_file_strict("file.ts", "const Worker = class Internal { run() {} }; const task = function privateName() {}; const arrow = () => 1; const obj = { run() {} }; function outer() { class Nested { run() {} } }");
    assert_eq!(evidence["status"], "succeeded", "{evidence}");
    let functions = evidence["declarationScopes"]["functions"].as_array().unwrap();
    for name in ["task", "arrow"] {
        assert!(functions.iter().any(|f| f["name"] == name && f["scope"]["kind"] == "file"), "{evidence}");
    }
    assert!(!functions.iter().any(|f| f["name"] == "privateName"));
    let runs: Vec<_> = functions.iter().filter(|f| f["name"] == "run").collect();
    assert_eq!(runs.iter().filter(|f| f["scope"]["kind"] == "local").count(), 2, "{evidence}");
    assert!(runs.iter().any(|f| f["scope"]["kind"] == "class" && f["scope"]["name"] == "Worker"), "{evidence}");
    let classes = evidence["declarationScopes"]["classes"].as_array().unwrap();
    assert!(classes.iter().any(|c| c["name"] == "Worker" && c["scope"]["kind"] == "file"));
    assert!(!classes.iter().any(|c| c["name"] == "Internal"));
}

#[test]
#[ignore = "requires pinned grammars; run with UA_TEST_PARSER_CACHE"]
fn coverage_gaps_keep_parameter_properties_and_computed_members_in_their_owner_scope() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let result = analyze_file_strict("file.ts", "abstract class Worker { constructor(public callback: () => void) {} abstract run(): void; [key]() {} } function ordinary(value: string) { return value; }");
    assert_eq!(result["status"], "succeeded", "{result}");
    let gaps = result["declarationScopes"]["coverageGaps"].as_array().unwrap();
    let parameter = gaps.iter().find(|gap| gap["reason"] == "Parameter-property callability is not covered by structural extraction").unwrap();
    assert_eq!(parameter["name"], "callback");
    assert_eq!(parameter["scope"]["kind"], "class");
    assert_eq!(parameter["scope"]["name"], "Worker");
    assert!(gaps.iter().any(|gap| gap["name"].is_null() && gap["reason"] == "Unresolved declaration name" && gap["scope"]["name"] == "Worker"));
    assert!(gaps.iter().any(|gap| gap["name"] == "run" && gap["scope"]["name"] == "Worker"));
    assert!(!gaps.iter().any(|gap| gap["name"] == "value"));
}

#[test]
#[ignore = "requires pinned grammars; run with UA_TEST_PARSER_CACHE"]
fn ordinary_identifiers_and_references_are_not_declaration_gaps() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for (path, source) in [
        ("file.ts", "export function run(value: string) { return helper(value); }"),
        ("file.py", "def run(value):\n    return helper(value)\n"),
    ] {
        let result = analyze_file_strict(path, source);
        assert_eq!(result["status"], "succeeded");
        assert_eq!(result["declarationScopes"]["coverageGaps"], serde_json::json!([]), "{result}");
    }
}

#[test]
#[ignore = "requires pinned Ruby grammar; run with UA_TEST_PARSER_CACHE"]
fn ruby_runtime_evidence_tracks_accessors_aliases_and_unresolved_installers() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let result = analyze_file_strict("file.rb", r#"
class Worker
  attr_reader :name
  attr_writer :token
  attr_accessor :value
  attr :enabled, true
  attr :flag, false
  attr_writer dynamic_name
  define_method(:run) { 1 }
  define_singleton_method(:build) { new }
  alias renamed run
  alias_method :copied, :run
  class << Other
    attr_reader :singleton_value
  end
end
Other.attr_reader :alien
installer = Worker.method(:define_method)
eval(source)
text = "attr_accessor :fake"
"#);
    assert_eq!(result["status"], "succeeded", "{result}");
    let effects = result["declarationScopes"]["effects"].as_array().unwrap();
    for name in ["name", "token=", "value", "value=", "enabled", "enabled=", "flag", "run", "self.build", "renamed", "copied"] {
        assert!(effects.iter().any(|e| e["name"] == name && e["scope"]["kind"] == "class" && e["scope"]["name"] == "Worker"), "missing {name}: {result}");
    }
    for name in ["token", "flag=", "fake"] {
        assert!(!effects.iter().any(|e| e["name"] == name), "unexpected {name}: {result}");
    }
    assert!(effects.iter().any(|e| e["name"].is_null() && e["nameSuffix"] == "=" && e["scope"]["name"] == "Worker"));
    assert!(effects.iter().any(|e| e["name"] == "alien" && e["scope"]["kind"] == "unknown"));
    assert!(effects.iter().any(|e| e["name"] == "singleton_value" && e["scope"]["kind"] == "unknown"));
    assert!(effects.iter().any(|e| e["reason"] == "Indirect method installer"));
    assert!(effects.iter().any(|e| e["reason"] == "Dynamic dispatch or code evaluation" && e["kind"].is_null()));
}
