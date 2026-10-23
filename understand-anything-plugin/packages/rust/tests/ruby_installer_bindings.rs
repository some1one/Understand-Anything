use serde_json::json;
use understand_anything::{
    incremental_symbols::compare_file_symbols, parsers, structure::analyze_file_strict,
};
#[test]
#[ignore = "requires pinned Ruby grammar; run with UA_TEST_PARSER_CACHE"]
fn ruby_runtime_installers_resolve_declared_receivers_without_guessing_aliases() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let before = analyze_file_strict(
        "file.rb",
        "class A\n def run; end\nend\nclass B\n def keep; end\nend",
    );
    for installer in ["attr_reader", "define_method"] {
        for receiver in ["A", "B", "target"] {
            for (name, matching) in [
                ("\"run\"", true),
                ("\"other\"", false),
                ("(\"r\" + \"un\")", true),
            ] {
                let code = format!("class A\n def keep; end\nend\nclass B\n def keep; end\nend\n{receiver}.{installer}({name}) {{ 1 }}");
                let after = analyze_file_strict("file.rb", &code);
                assert_eq!(after["status"], "succeeded", "{code}: {after}");
                let report = compare_file_symbols(
                    "file.rb",
                    &json!({"nodes":[{"id":"old","type":"function","name":"A.run","filePath":"file.rb"}],"edges":[]}),
                    &json!({"nodes":[],"edges":[]}),
                    &before,
                    &after,
                );
                let expected = if matching && receiver != "B" {
                    "unknown"
                } else {
                    "deleted"
                };
                assert_eq!(report["missing"][0]["status"], expected, "{code}: {report}");
            }
        }
    }
    for code in [
        "class A; end\nclass B; end\nB = external\nB.attr_reader(:run)",
        "class A; end\nclass B; end\nreceiver = B\nreceiver.attr_reader(:run)",
        "class A; end\nclass B; end\ndef install(receiver)\n receiver.attr_reader(:run)\nend",
    ] {
        let after = analyze_file_strict("file.rb", code);
        let report = compare_file_symbols(
            "file.rb",
            &json!({"nodes":[{"id":"old","type":"function","name":"A.run","filePath":"file.rb"}],"edges":[]}),
            &json!({"nodes":[],"edges":[]}),
            &before,
            &after,
        );
        assert_eq!(
            report["missing"][0]["status"], "unknown",
            "{code}: {report}"
        );
    }
}
