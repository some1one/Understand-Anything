use serde_json::{Value, json};
use std::{fs, process::Command};
use understand_anything::persistence::{read_json, write_json};
fn node(path: &str, summary: &str) -> Value {
    json!({"id":format!("file:{path}"),"type":"file","name":path,"filePath":path,"summary":summary,"tags":[]})
}
#[test]
fn existing_baseline_is_merged_before_numeric_batches_and_survives_empty_plans() {
    for data_dir in [".ua", ".understand-anything"] {
        let temp = tempfile::tempdir().unwrap();
        let inter = temp.path().join(data_dir).join("intermediate");
        fs::create_dir_all(&inter).unwrap();
        let baseline =
            json!({"nodes":[node("unchanged.ts","retained"),node("shared.ts","old")],"edges":[]});
        write_json(&inter.join("batch-existing.json"), &baseline).unwrap();
        write_json(&inter.join("batch-0.json"),&json!({"nodes":[node("shared.ts","fresh"),node("new.ts","new")],"edges":[{"source":"file:new.ts","target":"file:unchanged.ts","type":"imports","direction":"forward","weight":0.8}]})).unwrap();
        let run = || {
            Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
                .arg("merge_batch_graphs")
                .arg(temp.path())
                .output()
                .unwrap()
        };
        let output = run();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(!String::from_utf8_lossy(&output.stderr).contains("unrecognized filenames"));
        let graph = read_json(&inter.join("assembled-graph.json")).unwrap();
        assert_eq!(graph["nodes"].as_array().unwrap().len(), 3);
        assert_eq!(
            graph["nodes"]
                .as_array()
                .unwrap()
                .iter()
                .find(|n| n["id"] == "file:shared.ts")
                .unwrap()["summary"],
            "fresh"
        );
        assert!(
            graph["edges"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["source"] == "file:new.ts" && e["target"] == "file:unchanged.ts")
        );
        fs::rename(inter.join("batch-0.json"), inter.join("saved-fresh.json")).unwrap();
        write_json(
            &inter.join("batches.json"),
            &json!({"batches":[],"totalBatches":0}),
        )
        .unwrap();
        assert!(run().status.success());
        assert_eq!(
            read_json(&inter.join("assembled-graph.json")).unwrap()["nodes"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        write_json(
            &inter.join("batch-existing.json"),
            &json!({"nodes":[],"edges":[]}),
        )
        .unwrap();
        let empty = run();
        assert!(empty.status.success());
        assert!(!String::from_utf8_lossy(&empty.stderr).contains("contributed 0 nodes"));
        assert_eq!(
            read_json(&inter.join("assembled-graph.json")).unwrap()["nodes"],
            json!([])
        );
        let previous = fs::read(inter.join("assembled-graph.json")).unwrap();
        for invalid in ["{", "{}", "{\"nodes\":[],\"edges\":null}"] {
            fs::write(inter.join("batch-existing.json"), invalid).unwrap();
            assert!(!run().status.success());
            assert_eq!(
                fs::read(inter.join("assembled-graph.json")).unwrap(),
                previous
            );
        }
    }
}
