use serde_json::json;
use understand_anything::imports::parse_tsconfig_text;

#[test]
fn jsonc_preserves_aliases_urls_escapes_and_unicode() {
    let config = parse_tsconfig_text(concat!(
        "\u{feff}",
        r#"{
      // Comment before options
      "compilerOptions": {
        "baseUrl": "https://example.org/a//b",
        "paths": {
          "@/*": ["src/*",], /* comment after trailing comma */
          "escaped": ["quote\"//literal", "C:\\src\\*", "文字/*", ",}"],
        },
      },
    }"#
    ))
    .unwrap();
    assert_eq!(config["baseUrl"], "https://example.org/a//b");
    assert_eq!(config["paths"]["@/*"], json!(["src/*"]));
    assert_eq!(
        config["paths"]["escaped"],
        json!(["quote\"//literal", "C:\\src\\*", "文字/*", ",}"])
    );
}

#[test]
fn malformed_jsonc_is_not_silently_repaired_into_different_values() {
    for source in [
        r#"{"compilerOptions":{}} /* unfinished"#,
        r#"{"compilerOptions":{"baseUrl":1/* separator */2}}"#,
        r#"{"compilerOptions":{"baseUrl":"unterminated}}"#,
    ] {
        assert!(parse_tsconfig_text(source).is_none(), "{source}");
    }
    assert!(parse_tsconfig_text("{\r// comment\r\"compilerOptions\":{},\r}").is_some());
}
