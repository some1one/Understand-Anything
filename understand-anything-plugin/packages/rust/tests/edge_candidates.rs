use serde_json::json;
use std::collections::BTreeSet;
use understand_anything::batch_merge::{merge_and_normalize, merge_with_edge_candidates};

#[test]
fn preserves_only_normalized_current_missing_target_evidence() {
    let old = json!({"nodes":[],"edges":[{"source":"file:a.rs","target":"function:old","type":"calls","weight":99}]});
    let fresh = json!({"nodes":[{"id":"project:file:a.rs","type":"file","filePath":"a.rs"}],"edges":[
        {"source":"project:file:a.rs","target":"function:missing","type":"calls","direction":"both","weight":1,"description":"weaker"},
        {"source":"project:file:a.rs","target":"function:missing","type":"calls","direction":"mutual","weight":2,"description":"stronger"},
        {"source":"project:file:a.rs","target":"function:missing","type":"calls","direction":"forward"},
        {"source":"file:missing","target":"file:a.rs","type":"calls"},
        {"source":"file:a.rs","target":"function:missing","type":"tested_by"},
        {"source":"file:a.rs","target":"file:a.rs","type":"calls"}
    ]});
    let batches = vec![old, fresh];
    let (graph, report, candidates) = merge_with_edge_candidates(&batches, &BTreeSet::from([1]));
    assert_eq!((graph.clone(), report), merge_and_normalize(&batches));
    assert_eq!(graph["edges"].as_array().unwrap().len(), 1);
    assert_eq!(candidates.len(), 2);
    assert_eq!(candidates[0]["source"], "file:a.rs");
    assert_eq!(candidates[0]["direction"], "bidirectional");
    assert_eq!(candidates[0]["description"], "stronger");
    assert_eq!(candidates[1]["direction"], "forward");
    assert!(merge_with_edge_candidates(&batches, &BTreeSet::new()).2.is_empty());
}
