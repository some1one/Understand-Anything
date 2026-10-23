use serde_json::json;
use understand_anything::updates::refresh_graph_imports;

#[test]
fn refreshed_imports_replace_stale_edges_without_removing_other_relationships() {
    let graph = json!({"nodes":[
        {"id":"config:a","type":"config","filePath":"a"},
        {"id":"schema:b","type":"schema","filePath":"b"},
        {"id":"file:c","type":"file","filePath":"c"},
        {"id":"function:a:f","type":"function","filePath":"a"}
    ],"edges":[
        {"source":"config:a","target":"schema:b","type":"imports"},
        {"source":"config:a","target":"schema:b","type":"depends_on","note":"keep"},
        {"source":"schema:b","target":"config:a","type":"imports","note":"unchanged"},
        {"source":"function:a:f","target":"schema:b","type":"calls"}
    ]});
    let map = json!({"a":["c","c","a","missing"]});
    let result = refresh_graph_imports(&graph, &map, &["a".into()]).unwrap();
    let edges = result["edges"].as_array().unwrap();
    assert_eq!(edges.len(), 4);
    assert!(!edges.iter().any(|e| e["source"]=="config:a" && e["target"]=="schema:b" && e["type"]=="imports"));
    for retained in &graph["edges"].as_array().unwrap()[1..] { assert!(edges.contains(retained)); }
    assert!(edges.iter().any(|e| e["source"]=="config:a" && e["target"]=="file:c" && e["recoveredFromImportMap"]==true));
    assert_eq!(refresh_graph_imports(&result, &map, &["a".into()]).unwrap(), result);
    assert!(refresh_graph_imports(&graph, &json!({}), &["a".into()]).is_err());
}
