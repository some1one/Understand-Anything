use serde_json::json;
use std::{fs, path::Path, process::Command};
use understand_anything::{incremental_symbols::validate_part_replacement, persistence::{read_json,write_json}};
fn git(root: &Path,args:&[&str])->String {
    let out=Command::new("git").args(args).current_dir(root).output().unwrap();
    assert!(out.status.success()); String::from_utf8(out.stdout).unwrap().trim().into()
}
#[test]
#[ignore="requires pinned TypeScript grammar; run with UA_TEST_PARSER_CACHE"]
fn partition_writer_blocks_omission_and_stub_substitution_without_destroying_evidence() {
    let cache=std::env::var("UA_TEST_PARSER_CACHE").unwrap();
    let tmp=tempfile::tempdir().unwrap(); let root=tmp.path();
    git(root,&["init","-q"]); git(root,&["config","user.name","Test"]); git(root,&["config","user.email","test@example.com"]);
    fs::write(root.join("a.ts"),"function run() {} function keep() {}\n").unwrap();
    git(root,&["add","."]);git(root,&["commit","-qm","base"]);let head=git(root,&["rev-parse","HEAD"]);
    let inter=root.join(".ua/intermediate");let parts=root.join(".ua/partitions");
    fs::create_dir_all(inter.join("part-files")).unwrap();fs::create_dir_all(&parts).unwrap();
    fs::write(inter.join("part-files/src.txt"),"a.ts\n").unwrap();
    let file=json!({"id":"file:a.ts","type":"file","filePath":"a.ts"});
    let symbol=json!({"id":"function:a.ts:run","type":"function","name":"run","filePath":"a.ts"});
    let old=json!({"project":{"gitCommitHash":head},"nodes":[file,symbol],"edges":[]});
    let saved=parts.join("src.knowledge-graph.json");write_json(&saved,&old).unwrap();let bytes=fs::read(&saved).unwrap();
    write_json(&inter.join("scan-result.json"),&json!({"files":[{"path":"a.ts"}]})).unwrap();
    write_json(&inter.join("batch-0.json"),&json!({"evidence":true})).unwrap();
    let mut stub=symbol.clone();stub["stub"]=json!(true);
    let run=||Command::new(env!("CARGO_BIN_EXE_understand-anything-rs")).args(["--parser-cache-dir",&cache,"assemble_part_graph",root.to_str().unwrap(),"src",&head]).output().unwrap();
    for nodes in [json!([file]),json!([file,stub])] {
        write_json(&inter.join("assembled-graph.json"),&json!({"nodes":nodes,"edges":[]})).unwrap();
        let out=run();assert!(!out.status.success());
        assert_eq!(fs::read(&saved).unwrap(),bytes);
        assert!(inter.join("batch-0.json").exists());assert!(inter.join("assembled-graph.json").exists());
        assert_eq!(read_json(&inter.join("part-symbol-report-src.json")).unwrap()["ok"],false);
    }
    let mut renamed=symbol;renamed["id"]=json!("function:a.ts:run:new");
    write_json(&inter.join("assembled-graph.json"),&json!({"nodes":[file,renamed],"edges":[]})).unwrap();
    let out=run();assert!(out.status.success(),"{}",String::from_utf8_lossy(&out.stderr));
    assert_eq!(read_json(&saved).unwrap()["nodes"][1]["id"],"function:a.ts:run:new");
    assert!(!inter.join("batch-0.json").exists());
}
#[test]
fn scope_removal_is_allowed_but_failed_scans_and_inconsistent_inventories_are_not() {
    let tmp=tempfile::tempdir().unwrap();let root=tmp.path();
    fs::create_dir_all(root.join(".ua/intermediate/part-files")).unwrap();
    fs::write(root.join(".ua/intermediate/part-files/src.txt"),"").unwrap();
    let old=json!({"nodes":[{"id":"f","type":"function","filePath":"removed.ts"}],"edges":[]});
    let current=json!({"nodes":[],"edges":[]});
    assert!(validate_part_replacement(root,"src",&old,&current,&json!({"files":[]})).is_ok());
    assert!(validate_part_replacement(root,"src",&old,&current,&json!({"files":[],"failures":[{"path":"removed.ts"}]})).is_err());
    fs::write(root.join(".ua/intermediate/part-files/src.txt"),"removed.ts\n").unwrap();
    assert!(validate_part_replacement(root,"src",&old,&current,&json!({"files":[]})).is_err());
}
