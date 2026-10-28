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
fn binary_defaults_cover_assets_without_excluding_scripts_or_source_extensions() {
    let temp = tempfile::tempdir().unwrap();
    let filter = create_ignore_filter_with_patterns(temp.path(), &[]).unwrap();
    for path in [
        "assets/photo.PNG", "assets/photo.HeIc", "assets/texture.dds",
        "native/tool.EXE", "native/plugin.DlL", "native/lib.a", "native/file.obj",
        "native/libcodec.so.2.4", "native/libcodec.2.dylib", "native/module.wasm",
        "java/Example.class", "python/module.PYC", "debug/symbols.pdb",
        "archives/source.tar.GZ", "archives/source.TAR.Xz", "archives/source.tar.zst",
        "archives/source.7Z", "archives/pkg.whl", "archives/app.jar", "archives/app.apk",
        "audio/music.FLAC", "audio/speech.opus", "audio/clip.WaV", "audio/score.mid",
        "video/clip.MOV", "video/clip.webm", "video/stream.m2ts",
        "fonts/text.OTF", "fonts/text.WOFF2", "fonts/collection.ttc",
        "documents/manual.PDF", "documents/report.docx", "documents/report.xlsx",
    ] {
        assert!(filter.is_ignored(path), "binary should be ignored: {path}");
    }
    for path in [
        "scripts/run.sh", "scripts/run.bash", "scripts/run.zsh", "scripts/run.fish",
        "scripts/run.py", "scripts/run.rb", "scripts/run.pl", "scripts/run.lua",
        "scripts/run.ps1", "scripts/run.bat", "scripts/run.cmd",
        "src/main.js", "src/main.mjs", "src/main.cjs", "src/main.ts", "src/main.mts",
        "src/main.cts", "src/main.tsx", "src/main.rs", "src/main.go", "src/main.java",
        "src/main.c", "src/main.cpp", "src/main.cs", "src/main.swift", "src/main.kt",
        "src/main.s", "src/main.S", "src/main.asm", "src/main.R", "schema.sql",
        "go.mod", "settings.json", "settings.yaml", "native/bindings.so.py",
    ] {
        assert!(!filter.is_ignored(path), "source should remain eligible: {path}");
    }
}

#[test]
fn scanner_skips_binary_assets_and_user_negation_can_restore_one() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    fs::create_dir(root.join("assets")).unwrap();
    for name in ["photo.PNG", "plugin.dll", "library.so.3", "bundle.tar.zst", "sound.flac", "font.otf"] {
        fs::write(root.join("assets").join(name), [0, 255, 254, 0]).unwrap();
    }
    for name in ["run.sh", "run.py", "main.ts", "go.mod"] {
        fs::write(root.join(name), "source\n").unwrap();
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(root.join("run.sh"), fs::Permissions::from_mode(0o755)).unwrap();
    }
    let scan = scan_project(root).unwrap();
    let files: Vec<_> = scan["files"].as_array().unwrap().iter().map(|file| file["path"].as_str().unwrap()).collect();
    assert_eq!(files, vec!["go.mod", "main.ts", "run.py", "run.sh"]);
    assert_eq!(scan["filteredByIgnore"], 0);
    fs::create_dir(root.join(".ua")).unwrap();
    fs::write(root.join(".ua/.uaignore"), "!assets/photo.PNG\n").unwrap();
    let included = scan_project(root).unwrap();
    assert_eq!(included["totalFiles"], 5);
    assert!(included["files"].as_array().unwrap().iter().any(|file| file["path"] == "assets/photo.PNG"));
    assert_eq!(included["filteredByIgnore"], 0);
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
