use serde_json::json;
use understand_anything::{batch_merge::{whole_file_node_index, recover_imports_from_scan}, persistence::write_json};

#[test]
fn canonical_index_excludes_children_and_prefers_file_nodes() {
    let nodes = json!([
        {"id":"config:a.yaml","type":"config","filePath":"a.yaml"},
        {"id":"file:a.yaml","type":"file","filePath":"a.yaml"},
        {"id":"table:b.sql:users","type":"table","filePath":"b.sql"},
        {"id":"endpoint:c.yaml:get","type":"endpoint","filePath":"c.yaml"},
        {"id":"service:d.yaml:worker","type":"service","filePath":"d.yaml"},
        {"id":"schema:b.sql","type":"schema","filePath":"b.sql"}
    ]);
    let (index, warnings) = whole_file_node_index(nodes.as_array().unwrap());
    assert_eq!(index.len(), 2);
    assert_eq!(index["a.yaml"], "file:a.yaml");
    assert_eq!(index["b.sql"], "schema:b.sql");
    assert_eq!(warnings.len(), 1);
}
#[test]
fn recovery_uses_whole_file_types_and_retains_boundary_stub_behavior() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("scan.json");
    write_json(&path, &json!({"files":[{"path":"external.rb"}],
        "importMap":{"app.yaml":["schema.sql","external.rb"],"stub.rb":["app.yaml"]}})).unwrap();
    let mut graph = json!({"nodes":[
        {"id":"config:app.yaml","type":"config","filePath":"app.yaml"},
        {"id":"schema:schema.sql","type":"schema","filePath":"schema.sql"},
        {"id":"file:stub.rb","type":"file","filePath":"stub.rb","stub":true}
    ],"edges":[]});
    assert_eq!(recover_imports_from_scan(&mut graph, &path).0, 2);
    assert_eq!(recover_imports_from_scan(&mut graph, &path).0, 0);
    assert!(graph["edges"].as_array().unwrap().iter().any(|e| e["source"] == "config:app.yaml" && e["target"] == "schema:schema.sql"));
    assert!(graph["nodes"].as_array().unwrap().iter().any(|n| n["id"] == "file:external.rb" && n["stub"] == true));
}
