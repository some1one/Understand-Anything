mod common;
use serde_json::{Value, json};
use std::{collections::BTreeSet, fs};
use understand_anything as ua;

#[cfg(unix)]
#[test]
fn context_tree_preserves_literal_backslashes_in_filenames() {
    if common::with_dictionaries("context_tree_preserves_literal_backslashes_in_filenames") {
        return;
    }
    let temp = tempfile::tempdir().unwrap();
    fs::create_dir(temp.path().join("src")).unwrap();
    fs::write(temp.path().join("src/name\\part.rs"), "").unwrap();
    assert_eq!(
        ua::context_helpers::shallow_tree(temp.path()),
        vec!["src/name\\part.rs"]
    );
}

#[test]
fn captured_python_query_behavior_is_preserved() {
    if common::with_dictionaries("captured_python_query_behavior_is_preserved") {
        return;
    }
    let fixtures: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/query_reference.json")).unwrap();
    for case in fixtures {
        let actual = ua::query_graph::build_payload(
            &case["graph"],
            case["query"].as_str().unwrap(),
            &BTreeSet::new(),
        )
        .unwrap();
        assert_eq!(actual, case["expected"], "query: {}", case["query"]);
    }
}
#[test]
fn payload_limit_covers_unicode_layers_neighbors_and_long_ids() {
    if common::with_dictionaries("payload_limit_covers_unicode_layers_neighbors_and_long_ids") {
        return;
    }
    let nodes:Vec<_>=(0..100).map(|i|json!({"id":format!("file:{i}.py"),"name":if i==0 {"needle"} else {"neighbor"},"summary":"文".repeat(10000)})).collect();
    let graph = json!({"project":{"description":"文".repeat(100000)},"nodes":nodes,
        "edges":(1..100).map(|i|json!({"source":"file:0.py","target":format!("file:{i}.py"),"type":"imports"})).collect::<Vec<_>>(),
        "layers":[{"id":"all","name":"All","nodeIds":(0..20001).map(|i|format!("file:{i}.py")).collect::<Vec<_>>()}]});
    let payload = ua::query_graph::build_payload(&graph, "needle", &BTreeSet::new()).unwrap();
    assert!(
        ua::query_graph::serialize(&payload).unwrap().len() <= ua::query_graph::MAX_PAYLOAD_BYTES
    );
    let selected: BTreeSet<_> = ["matchedNodes", "connectedNodes"]
        .iter()
        .flat_map(|k| ua::array(&payload, k))
        .filter_map(|n| n["id"].as_str())
        .collect();
    for edge in ua::array(&payload, "edges") {
        assert!(selected.contains(edge["source"].as_str().unwrap()));
        assert!(selected.contains(edge["target"].as_str().unwrap()));
    }
    assert_eq!(payload["layers"][0]["totalMembers"], 20001);
    let huge = json!({"nodes":[{"id":"x".repeat(100000),"summary":"文".repeat(100000)}]});
    let payload =
        ua::query_graph::build_payload(&huge, &"文".repeat(50000), &BTreeSet::new()).unwrap();
    assert!(
        ua::query_graph::serialize(&payload).unwrap().len() <= ua::query_graph::MAX_PAYLOAD_BYTES
    );
}
#[test]
fn cache_reader_never_requires_cspell_source_and_rejects_stale_or_corrupt_data() {
    if common::with_dictionaries(
        "cache_reader_never_requires_cspell_source_and_rejects_stale_or_corrupt_data",
    ) {
        return;
    }
    let temp = tempfile::tempdir().unwrap();
    let graph = temp.path().join("knowledge-graph.json");
    let dir = temp.path().join("query-dictionaries");
    fs::create_dir(&dir).unwrap();
    let raw = b"{}";
    let words = b"[\"GET\"]";
    let digest = ua::query_dictionary::hash(words);
    let filename = format!("python-{digest}.json");
    fs::write(dir.join(&filename), words).unwrap();
    fs::write(
        dir.join("manifest.json"),
        serde_json::to_vec(
            &json!({"version":3,"lemmaSha256":ua::query_dictionary::hash(&serde_json::to_vec(&ua::dictionary_data::Sources::open().unwrap().lemmas().unwrap()).unwrap()),"graphSha256":ua::query_dictionary::hash(raw),
        "dictionaries":{"python":{"file":filename,"sha256":digest}}}),
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(
        ua::query_dictionary::cached_words(&graph, raw),
        BTreeSet::from(["GET".into()])
    );
    assert!(ua::query_dictionary::cached_words(&graph, b"{\"nodes\":[]}").is_empty());
    fs::write(dir.join(filename), b"[]").unwrap();
    assert!(ua::query_dictionary::cached_words(&graph, raw).is_empty());
}
#[test]
fn indexing_and_search_share_unicode_graph_vocabulary() {
    if common::with_dictionaries("indexing_and_search_share_unicode_graph_vocabulary") {
        return;
    }
    let graph = json!({"nodes":[{"id":"unicode","name":"ＧＥＴ Straße HTTPServer","filePath":"src/my_checks.py"}]});
    let words = ua::query_dictionary::graph_vocabulary(&graph);
    for name in ["get", "strasse", "http", "server", "checks"] {
        assert!(words.contains(name), "{name}");
    }
    let lexicon = ua::query_terms::Lexicon::load().unwrap();
    assert_eq!(
        lexicon
            .matching_nodes(&graph, "ＧＥＴ requests", &BTreeSet::new())
            .len(),
        1
    );
}
