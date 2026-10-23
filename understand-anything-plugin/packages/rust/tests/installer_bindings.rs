use serde_json::{Value, json};
use understand_anything::{
    incremental_symbols::compare_file_symbols, parsers, structure::analyze_file_strict,
};
fn configure() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
}
fn classify(path: &str, before: &str, after: &str) -> Value {
    compare_file_symbols(
        path,
        &json!({"nodes":[{"id":"old","type":"function","name":"A.run","filePath":path}],"edges":[]}),
        &json!({"nodes":[],"edges":[]}),
        &analyze_file_strict(path, before),
        &analyze_file_strict(path, after),
    )
}
#[test]
#[ignore = "requires pinned JS/TS grammars; run with UA_TEST_PARSER_CACHE"]
fn standard_installers_have_exact_names_and_lexical_owners() {
    configure();
    for extension in ["js", "jsx", "ts", "tsx"] {
        let path = format!("file.{extension}");
        for (operation, expected) in [
            (
                "Object.defineProperty(A.prototype, 'run', descriptor);",
                "unknown",
            ),
            (
                "Object.defineProperty(A.prototype, 'other', descriptor);",
                "deleted",
            ),
            (
                "Object.defineProperty(B.prototype, 'run', descriptor);",
                "deleted",
            ),
            (
                "Object.defineProperties(A.prototype, {other: descriptor});",
                "deleted",
            ),
            (
                "Object.defineProperties(A.prototype, {[key]: descriptor});",
                "unknown",
            ),
            ("Reflect.set(B.prototype, 'run', value);", "deleted"),
            (
                "Reflect.defineProperty(A.prototype, 'run', descriptor);",
                "unknown",
            ),
            ("Object.assign(A.prototype, {other() {}});", "deleted"),
            ("Object.assign(A.prototype, {run() {}});", "unknown"),
            ("Object.assign(A.prototype, methods);", "unknown"),
            ("Reflect.get(A.prototype, 'run');", "deleted"),
            (
                "const install = Object.defineProperty; install(A, 'other', descriptor);",
                "unknown",
            ),
            (
                "Object.defineProperty(A.prototype, 'other', descriptor); const Object = custom;",
                "unknown",
            ),
            (
                "function setup(Object) { Object.defineProperty(A.prototype, 'other', descriptor); }",
                "unknown",
            ),
            (
                "{ let Object; } Object.defineProperty(A.prototype, 'other', descriptor);",
                "deleted",
            ),
            (
                "{ var Object; } Object.defineProperty(A.prototype, 'other', descriptor);",
                "unknown",
            ),
            (
                "function setup() { let Object; } Object.defineProperty(A.prototype, 'other', descriptor);",
                "deleted",
            ),
            (
                "function setup(B) { Object.defineProperty(B.prototype, 'run', descriptor); }",
                "unknown",
            ),
            (
                "function setup() { class B {} Object.defineProperty(B.prototype, 'run', descriptor); }",
                "deleted",
            ),
            (
                "Object.defineProperty(B.prototype, 'run', descriptor); B = A;",
                "unknown",
            ),
            (
                "for (B of values) {} Object.defineProperty(B.prototype, 'run', descriptor);",
                "unknown",
            ),
            (
                "for (Object of values) {} Object.defineProperty(A.prototype, 'other', descriptor);",
                "unknown",
            ),
            (
                "const {Object} = custom; Object.defineProperty(A.prototype, 'other', descriptor);",
                "unknown",
            ),
            (
                "import {custom as Object} from 'custom'; Object.defineProperty(A.prototype, 'other', descriptor);",
                "unknown",
            ),
            (
                "with (custom) { Object.defineProperty(A.prototype, 'other', descriptor); }",
                "unknown",
            ),
            (
                "import Object from 'custom'; Object.defineProperty(A.prototype, 'other', descriptor);",
                "unknown",
            ),
            (
                "try {} catch (Object) { Object.defineProperty(A.prototype, 'other', descriptor); }",
                "unknown",
            ),
        ] {
            let after = format!("class A {{ keep() {{}} }} class B {{ keep() {{}} }} {operation}");
            let result = classify(&path, "class A { run() {} keep() {} }", &after);
            assert_eq!(
                result["missing"][0]["status"], expected,
                "{path}: {operation}\n{result}"
            );
        }
    }
}
#[test]
#[ignore = "requires pinned Python grammar; run with UA_TEST_PARSER_CACHE"]
fn python_setattr_respects_shadowing_imports_and_method_scope() {
    configure();
    for (operation, expected) in [
        ("setattr(A, 'run', callback)", "unknown"),
        ("setattr(A, 'other', callback)", "deleted"),
        ("setattr(B, 'run', callback)", "deleted"),
        ("setattr(A, 'other', callback)\nsetattr = custom", "unknown"),
        (
            "from custom import setattr\nsetattr(A, 'other', callback)",
            "unknown",
        ),
        (
            "from custom import *\nsetattr(A, 'other', callback)",
            "unknown",
        ),
        (
            "def setup(setattr):\n    setattr(A, 'other', callback)",
            "unknown",
        ),
        (
            "def setup():\n    setattr = custom\nsetattr(A, 'other', callback)",
            "deleted",
        ),
        (
            "install = setattr\ninstall(A, 'other', callback)",
            "unknown",
        ),
        (
            "class C:\n    setattr = custom\n    def setup(self):\n        setattr(A, 'other', callback)",
            "deleted",
        ),
    ] {
        let after =
            format!("class A:\n    def keep(self): pass\nclass B:\n    pass\n{operation}\n");
        let result = classify(
            "file.py",
            "class A:\n    def run(self): pass\n    def keep(self): pass\n",
            &after,
        );
        assert_eq!(
            result["missing"][0]["status"], expected,
            "{operation}\n{result}"
        );
    }
}

#[test]
#[ignore = "requires pinned TypeScript grammar; run with UA_TEST_PARSER_CACHE"]
fn typescript_runtime_namespaces_and_enums_shadow_standard_installers() {
    configure();
    for (prefix, expected) in [
        (
            "namespace Object { export function defineProperty() {} }",
            "unknown",
        ),
        ("enum Object { Custom }", "unknown"),
        ("namespace Helpers { const Object = custom; }", "deleted"),
    ] {
        let after = format!(
            "class A {{ keep() {{}} }} {prefix} Object.defineProperty(A.prototype, 'other', descriptor);"
        );
        let result = classify("file.ts", "class A { run() {} keep() {} }", &after);
        assert_eq!(
            result["missing"][0]["status"], expected,
            "{after}: {result}"
        );
    }
}
