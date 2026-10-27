use serde_json::{Value, json};
use std::{fs, process::Command};
use understand_anything::scan::{create_ignore_filter_with_patterns, scan_project, scan_project_with_patterns};
#[test]
fn invocation_patterns_override_user_rules_and_defaults_in_order() {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    fs::create_dir(root.join(".ua")).unwrap();
    fs::write(root.join(".ua/.uaignore"), "!docs/\n").unwrap();
    fs::write(root.join(".uaignore"), "fixtures/\n").unwrap();
    let filter = create_ignore_filter_with_patterns(root, &["docs/".into(),"!dist/".into(),"e2e/".into(),"!e2e/keep.ts".into()]).unwrap();
    assert!(filter.is_ignored("docs/README.md"));
    assert!(filter.is_ignored("fixtures/data.json"));
    assert!(filter.is_ignored("node_modules/lib.js"));
    assert!(!filter.is_ignored("dist/bundle.js"));
    assert!(filter.is_ignored("e2e/test.ts"));
    assert!(!filter.is_ignored("e2e/keep.ts"));
    assert!(!filter.is_ignored("src/main.ts"));
    assert_eq!(scan_project(root).unwrap(), scan_project_with_patterns(root, &[]).unwrap());
}
#[test]
fn cli_accepts_both_forms_repeated_flags_and_keeps_output_on_invalid_arguments() {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    for dir in ["src","docs","e2e"] { fs::create_dir(root.join(dir)).unwrap(); }
    for name in ["src/a.ts","docs/a.md","e2e/test.ts","e2e/keep.ts"] { fs::write(root.join(name), "sample\n").unwrap(); }
    let output_dir = tempfile::tempdir().unwrap(); let output = output_dir.path().join("scan.json");
    let run = |args: &[&str]| Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .arg("scan_project").arg(root).arg(&output).args(args).output().unwrap();
    assert!(run(&["--exclude= docs/ ,e2e/", "--exclude", "!e2e/keep.ts"]).status.success());
    let bytes = fs::read(&output).unwrap();
    let result: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(result["excludePatterns"],json!(["docs/","e2e/","!e2e/keep.ts"]));
    let paths: Vec<_> = result["files"].as_array().unwrap().iter().map(|f| f["path"].as_str().unwrap()).collect();
    assert_eq!(paths,vec!["e2e/keep.ts","src/a.ts"]);
    assert_eq!(result["filteredByIgnore"],2);
    for args in [vec!["--exclude"],vec!["--typo=docs/"]] {
        assert!(!run(&args).status.success());
        assert_eq!(fs::read(&output).unwrap(),bytes);
    }
}

#[test]
fn assembled_scan_preserves_invocation_scope_without_narrative_override() {
    let temp = tempfile::tempdir().unwrap(); let root = temp.path();
    fs::write(root.join("a.ts"), "hello").unwrap();
    let mut scan = scan_project_with_patterns(root, &["docs/".into()]).unwrap();
    let imports = json!({"importMap":{"a.ts":[]}});
    let narrative = json!({"excludePatterns":["wrong/"]});
    let assembled = understand_anything::assembly::assemble_scan_result(&scan,&imports,&narrative,root).unwrap();
    assert_eq!(assembled["excludePatterns"],json!(["docs/"]));
    scan["excludePatterns"] = json!("invalid");
    assert!(understand_anything::assembly::assemble_scan_result(&scan,&imports,&narrative,root).is_err());
}
