use serde_json::json;
use understand_anything::imports::{extract_import_map, select_analysis_files};

#[test]
fn selections_are_ordered_unique_and_do_not_require_parser_startup_for_empty_work() {
    let files =
        json!([{"path":"a.ts","fileCategory":"code"}, {"path":"README.md","fileCategory":"docs"}]);
    let inventory = files.as_array().unwrap();
    let selection = json!(["README.md", "a.ts", "README.md"]);
    let selected = select_analysis_files(inventory, Some(&selection)).unwrap();
    assert_eq!(selected, vec![&inventory[1], &inventory[0]]);
    assert_eq!(select_analysis_files(inventory, None).unwrap().len(), 2);
    let temp = tempfile::tempdir().unwrap();
    let result =
        extract_import_map(&json!({"projectRoot":temp.path(),"files":files,"analysisPaths":[]}))
            .unwrap();
    assert_eq!(result["stats"]["filesScanned"], 0);
    assert_eq!(result["importMap"], json!({}));
    let result = extract_import_map(
        &json!({"projectRoot":temp.path(),"files":files,"analysisPaths":["README.md"]}),
    )
    .unwrap();
    assert_eq!(result["stats"]["filesScanned"], 1);
    assert_eq!(result["importMap"], json!({"README.md":[]}));
}

#[test]
fn malformed_or_unknown_selectors_fail_before_reading_source() {
    let files = json!([{"path":"src/a.ts"}]);
    for paths in [
        json!(null),
        json!("src/a.ts"),
        json!([false]),
        json!([""]),
        json!(["../a.ts"]),
        json!(["src/../a.ts"]),
        json!(["/src/a.ts"]),
        json!(["missing.ts"]),
    ] {
        assert!(
            select_analysis_files(files.as_array().unwrap(), Some(&paths)).is_err(),
            "{paths}"
        );
    }
}

#[cfg(unix)]
#[test]
fn selection_preserves_unix_literal_backslashes_and_drive_like_names() {
    let files = json!([{"path":"C:\\a.ts"}, {"path":"a\\b.ts"}, {"path":"a/b.ts"}]);
    let paths = json!(["a\\b.ts", "C:\\a.ts"]);
    let selected = select_analysis_files(files.as_array().unwrap(), Some(&paths)).unwrap();
    assert_eq!(selected[0]["path"], "a\\b.ts");
    assert_eq!(selected[1]["path"], "C:\\a.ts");
}
