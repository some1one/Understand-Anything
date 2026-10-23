#[cfg(unix)]
#[test]
fn literal_backslash_paths_do_not_alias_directory_paths() {
    use serde_json::json;
    use understand_anything::imports::{ResolutionContext, resolve_ts_js_import, to_posix};
    let tmp = tempfile::tempdir().unwrap();
    let files = vec![
        json!({"path":"src/main.ts","language":"typescript"}),
        json!({"path":"src/a\\b.ts","language":"typescript"}),
        json!({"path":"src/a/b.ts","language":"typescript"}),
        json!({"path":"src/C:\\fixture.ts","language":"typescript"}),
    ];
    let mut context = ResolutionContext::new(tmp.path(), &files);
    assert_eq!(context.file_set.len(), 4);
    for (specifier, expected) in [
        ("./a\\b", "src/a\\b.ts"),
        ("./a/b", "src/a/b.ts"),
        ("./C:\\fixture", "src/C:\\fixture.ts"),
    ] {
        assert_eq!(
            resolve_ts_js_import(specifier, "src/main.ts", &mut context).as_deref(),
            Some(expected)
        );
    }
    assert_eq!(to_posix("\\literal.ts"), "\\literal.ts");
}
