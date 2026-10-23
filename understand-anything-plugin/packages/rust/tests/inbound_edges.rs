use serde_json::{Value, json};
use understand_anything::updates::restore_inbound_edges;
fn graph() -> Value {
    json!({"nodes":[
        {"id":"file:caller.rb","type":"file","filePath":"caller.rb"},
        {"id":"function:target.rb:run","type":"function","filePath":"target.rb"},
        {"id":"file:other.rb","type":"file","filePath":"other.rb"}
    ],"edges":[
        {"source":"file:caller.rb","target":"function:target.rb:run","type":"calls","weight":0.9,"description":"old inbound"},
        {"source":"function:target.rb:run","target":"file:other.rb","type":"calls","description":"old outgoing"}
    ]})
}
#[test]
fn unchanged_callers_keep_inbound_payloads_but_fresh_edges_take_precedence() {
    let old = graph();
    let changed = ["target.rb".into()].into();
    let mut new = old.clone();
    new["edges"] = json!([]);
    restore_inbound_edges(&old, &mut new, &changed).unwrap();
    assert_eq!(new["edges"], json!([old["edges"][0]]));
    restore_inbound_edges(&old, &mut new, &changed).unwrap();
    assert_eq!(new["edges"].as_array().unwrap().len(), 1);
    new["edges"][0]["description"] = json!("fresh inbound");
    new["edges"][0]["weight"] = json!(0.5);
    let fresh = new.clone();
    restore_inbound_edges(&old, &mut new, &changed).unwrap();
    assert_eq!(new, fresh);
}
#[test]
fn missing_targets_and_changed_callers_are_not_restored_and_reused_ids_fail() {
    let old = graph();
    let mut new = old.clone();
    new["edges"] = json!([]);
    restore_inbound_edges(&old, &mut new, &["caller.rb".into(), "target.rb".into()].into()).unwrap();
    assert_eq!(new["edges"], json!([]));
    new["nodes"][1]["filePath"] = json!("unrelated.rb");
    assert!(restore_inbound_edges(&old, &mut new, &["target.rb".into()].into()).is_err());
    assert_eq!(new["edges"], json!([]));
    new["nodes"].as_array_mut().unwrap().remove(1);
    restore_inbound_edges(&old, &mut new, &["target.rb".into()].into()).unwrap();
    assert_eq!(new["edges"], json!([]));
}

#[test]
fn batch_application_restores_inbound_edges_after_replacing_target_nodes() {
    let temp = tempfile::tempdir().unwrap();
    let data = temp.path().join(".ua");
    let inter = data.join("intermediate");
    std::fs::create_dir_all(&inter).unwrap();
    let old = graph();
    let write = understand_anything::persistence::write_json;
    write(&data.join("knowledge-graph.json"), &old).unwrap();
    write(&inter.join("change-analysis.json"), &json!({"filesToReanalyze":["target.rb"]})).unwrap();
    write(&inter.join("batch-0.json"), &json!({"nodes":[
        {"id":"file:target.rb","type":"file","filePath":"target.rb"},
        old["nodes"][1]
    ],"edges":[]})).unwrap();
    let merged = understand_anything::updates::apply_batches(temp.path()).unwrap();
    assert_eq!(merged["edges"], json!([old["edges"][0]]));
}
