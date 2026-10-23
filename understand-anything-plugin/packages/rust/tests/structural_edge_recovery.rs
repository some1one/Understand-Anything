use serde_json::json;
use understand_anything::merge::{merge_graphs_with_diagnostics, pending_structural_edges};

#[test]
fn cli_persists_retries_and_retires_recovered_edges() {
    use std::{fs, process::Command};
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join(".ua");
    fs::create_dir(&dir).unwrap();
    let config = tmp.path().join("dictionary-config.json");
    fs::write(&config, r#"{"version":1}"#).unwrap();
    let incoming = tmp.path().join("incoming.json");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .arg("merge_subdomain_graphs")
            .arg(tmp.path())
            .arg(&incoming)
            .env("UA_DICTIONARY_CONFIG", &config)
            .env(
                "UA_DICTIONARY_DIR",
                concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/dictionaries"),
            )
            .output()
            .unwrap()
    };
    fs::write(
        &incoming,
        json!({"nodes":[{"id":"domain:a","type":"domain","name":"A"}],
        "edges":[{"source":"domain:a","target":"flow:b","type":"contains_flow","weight":0.8}]})
        .to_string(),
    )
    .unwrap();
    let first = run();
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    let read = |name: &str| {
        serde_json::from_slice::<serde_json::Value>(&fs::read(dir.join(name)).unwrap()).unwrap()
    };
    assert_eq!(
        read("merge-report.json")["droppedEdges"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    // The first source fragment is gone: only the saved report can recover the edge.
    fs::write(
        &incoming,
        json!({"nodes":[{"id":"flow:b","type":"flow","name":"B"}],"edges":[]}).to_string(),
    )
    .unwrap();
    let second = run();
    assert!(
        second.status.success(),
        "{}",
        String::from_utf8_lossy(&second.stderr)
    );
    assert_eq!(read("merge-report.json")["recoveredStructuralEdges"], 1);
    assert_eq!(read("merge-report.json")["droppedEdges"], json!([]));
    assert_eq!(
        read("knowledge-graph.json")["edges"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    let saved = fs::read(dir.join("knowledge-graph.json")).unwrap();
    fs::write(dir.join("merge-report.json"), "{").unwrap();
    assert!(!run().status.success());
    assert_eq!(fs::read(dir.join("knowledge-graph.json")).unwrap(), saved);
}

#[test]
fn structural_drops_keep_payload_and_recover_when_endpoint_arrives() {
    let edge = json!({"source":"domain:a","target":"flow:b","type":"contains_flow",
        "weight":0.8,"description":"Preserve me","custom":{"evidence":"source"}});
    let source = json!({"nodes":[{"id":"domain:a","type":"domain"}],"edges":[edge]});
    let (first, warnings, dropped) = merge_graphs_with_diagnostics(&[source]);
    assert!(first["edges"].as_array().unwrap().is_empty());
    assert!(
        warnings
            .iter()
            .any(|line| line.starts_with("Warning: dropped structural edge"))
    );
    assert_eq!(dropped[0]["custom"], edge["custom"]);
    let pending = pending_structural_edges(&json!({"droppedEdges":dropped}));
    assert_eq!(pending, vec![edge.clone()]);
    let (recovered, _, dropped_again) = merge_graphs_with_diagnostics(&[
        first,
        json!({"nodes":[{"id":"flow:b","type":"flow"}],"edges":pending}),
    ]);
    assert_eq!(recovered["edges"], json!([edge]));
    assert!(dropped_again.is_empty());
}

#[test]
fn only_structural_edges_are_retried_and_duplicates_remain_unique() {
    let report = json!({"droppedEdges":[
        {"source":"a","target":"b","type":"flow_step","weight":0.5,"missing":["target 'b'"]},
        {"source":"a","target":"b","type":"cross_domain","weight":0.4},
        {"source":"a","target":"b","type":"calls","weight":1}
    ]});
    let pending = pending_structural_edges(&report);
    assert_eq!(pending.len(), 2);
    let graph = json!({"nodes":[{"id":"a"},{"id":"b"}],"edges":pending});
    let (merged, _, dropped) = merge_graphs_with_diagnostics(&[graph.clone(), graph]);
    assert_eq!(merged["edges"].as_array().unwrap().len(), 2);
    assert!(dropped.is_empty());
}
