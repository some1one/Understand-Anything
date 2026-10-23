use serde_json::json;
use understand_anything::batching::compute_batches;

#[test]
fn changed_targets_keep_full_graph_neighbor_context_and_batch_ids() {
    let temp = tempfile::tempdir().unwrap();
    let scan = json!({"files":[
        {"path":"src/a.ts","language":"typescript","fileCategory":"code"},
        {"path":"src/b.ts","language":"typescript","fileCategory":"code"}
    ],"importMap":{"src/a.ts":["src/b.ts"],"src/b.ts":[]}});
    let full = compute_batches(temp.path(), &scan, None);
    let changed = compute_batches(temp.path(), &scan, Some(&["./src//a.ts".into()].into()));
    let batch = &changed["batches"][0];
    assert_eq!(batch["files"].as_array().unwrap().len(), 1);
    assert_eq!(batch["files"][0]["path"], "src/a.ts");
    let original = full["batches"].as_array().unwrap().iter().find(|b| b["files"].as_array().unwrap().iter().any(|f| f["path"]=="src/b.ts")).unwrap();
    assert_eq!(batch["neighborMap"]["src/a.ts"][0]["path"], "src/b.ts");
    assert_eq!(batch["neighborMap"]["src/a.ts"][0]["batchIndex"], original["batchIndex"]);
    assert!(batch["batchImportData"].get("src/b.ts").is_none());
    assert!(batch["neighborMap"].get("src/b.ts").is_none());
    assert_eq!(compute_batches(temp.path(), &scan, Some(&Default::default()))["batches"], json!([]));
}
