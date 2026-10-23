use serde_json::{json, Value};
use understand_anything::updates::reconcile_layers;

fn file(id: &str, path: &str) -> Value {
    json!({"id":id,"type":"file","filePath":path})
}
fn member(layers: &[Value], node: &str) -> String {
    layers
        .iter()
        .find(|layer| layer["nodeIds"].as_array().unwrap().contains(&json!(node)))
        .unwrap()["id"]
        .as_str()
        .unwrap()
        .to_owned()
}
#[test]
fn placement_prefers_directory_then_distinct_connections_then_previous_order() {
    let nodes = vec![
        file("a", "src/a/base.rs"),
        file("b", "src/b/base.rs"),
        file("b2", "src/b/other.rs"),
        file("deep", "src/a/new.rs"),
        file("connected", "new.rs"),
        file("tie", "other.rs"),
    ];
    let layers = vec![
        json!({"id":"A","nodeIds":["a"]}),
        json!({"id":"B","nodeIds":["b","b2"]}),
    ];
    let edges = vec![
        json!({"source":"deep","target":"b"}),
        json!({"source":"connected","target":"a"}),
        json!({"source":"connected","target":"a"}),
        json!({"source":"b","target":"connected"}),
        json!({"source":"connected","target":"b2"}),
        json!({"source":"missing","target":"tie"}),
    ];
    let result = reconcile_layers(&nodes, &edges, &layers);
    assert_eq!(member(&result, "deep"), "A");
    assert_eq!(member(&result, "connected"), "B");
    assert_eq!(member(&result, "tie"), "A");
    assert_eq!(result.len(), 2);
}
#[test]
fn removes_stale_and_duplicate_members_and_only_falls_back_without_surviving_layers() {
    let nodes = vec![
        file("a", "src/a.rs"),
        file("new", "src/new.rs"),
        json!({"id":"function","type":"function","filePath":"src/a.rs"}),
    ];
    let layers = vec![
        json!({"id":"empty","nodeIds":["gone"]}),
        json!({"id":"keep","name":"Existing name","nodeIds":["a","a","function"]}),
        json!({"id":"duplicate","nodeIds":["a"]}),
    ];
    let result = reconcile_layers(&nodes, &[], &layers);
    assert_eq!(result.len(), 1);
    assert_eq!(result[0]["name"], "Existing name");
    assert_eq!(result[0]["nodeIds"], json!(["a", "function", "new"]));
    let fallback = reconcile_layers(&nodes, &[], &[]);
    assert_eq!(fallback.len(), 1);
    assert_eq!(fallback[0]["nodeIds"], json!(["a", "new"]));
}
