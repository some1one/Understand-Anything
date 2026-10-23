use serde_json::{Value,json};
use std::{fs,path::Path,process::Command};
use understand_anything::{persistence::{read_json,write_json},updates};
fn git(root:&Path,args:&[&str])->String {
    let out=Command::new("git").args(args).current_dir(root).output().unwrap();
    assert!(out.status.success());String::from_utf8(out.stdout).unwrap().trim().into()
}
#[test]
fn metadata_only_completion_refreshes_snapshot_identity_without_changing_graph_content() {
    let tmp=tempfile::tempdir().unwrap();let root=tmp.path();
    git(root,&["init","-q"]);git(root,&["config","user.name","Test"]);git(root,&["config","user.email","test@example.com"]);
    fs::write(root.join("file.rs"),"fn main() {}\n").unwrap();git(root,&["add","."]);git(root,&["commit","-qm","base"]);
    let head=git(root,&["rev-parse","HEAD"]);let data=root.join(".ua");let inter=data.join("intermediate");fs::create_dir_all(&inter).unwrap();
    let graph=json!({"version":"1.0.0","project":{"gitCommitHash":"old","analyzedAt":"old time","name":"Project","description":"Keep this","frameworks":["custom"],"languages":["obsolete"],"extension":42},"nodes":[{"id":"file:file.rs","type":"file","filePath":"file.rs"}],"edges":[],"layers":[],"custom":true});
    write_json(&data.join("knowledge-graph.json"),&graph).unwrap();
    write_json(&inter.join("auto-update-state.json"),&json!({"currentCommit":head,"changedSourceFiles":[]})).unwrap();
    write_json(&inter.join("scan-result.json"),&json!({"files":[{"language":"rust"},{"language":"python"},{"language":"rust"},{"language":""}]})).unwrap();
    let result=updates::fingerprint_check(root).unwrap();assert_eq!(result["action"],"SKIP");
    let saved=read_json(&data.join("knowledge-graph.json")).unwrap();
    for key in ["nodes","edges","layers","custom"] {assert_eq!(saved[key],graph[key]);}
    for key in ["name","description","frameworks","extension"] {assert_eq!(saved["project"][key],graph["project"][key]);}
    // Fresh inventory supersedes the stale cached Python entry.
    assert_eq!(saved["project"]["languages"],json!(["rust"]));
    assert_eq!(saved["project"]["gitCommitHash"],head);assert_ne!(saved["project"]["analyzedAt"],"old time");
    assert_eq!(read_json(&data.join("meta.json")).unwrap()["gitCommitHash"],head);
    let before=fs::read(data.join("meta.json")).unwrap();
    write_json(&data.join("knowledge-graph.json"),&Value::Null).unwrap();
    assert!(updates::fingerprint_check(root).is_err());
    assert_eq!(fs::read(data.join("meta.json")).unwrap(),before);
}
