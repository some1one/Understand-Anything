use serde_json::json;
use std::{cell::RefCell, fs, process::Command};
use ua::embeddings::{EmbeddingClient, EmbeddingResult};
use understand_anything as ua;
#[test]
fn injectable_embedding_client_preserves_batches_and_skips_empty_nodes() {
    struct Fake {
        calls: RefCell<Vec<Vec<String>>>,
    }
    impl EmbeddingClient for Fake {
        fn embed(&self, texts: &[String]) -> ua::Result<Vec<Vec<f64>>> {
            self.calls.borrow_mut().push(texts.to_vec());
            Ok(texts.iter().map(|s| vec![s.len() as f64, 1.]).collect())
        }
    }
    let fake = Fake {
        calls: RefCell::new(vec![]),
    };
    let nodes = vec![
        json!({"id":"1","name":"First","summary":"Detail","tags":["tag"]}),
        json!({"id":"2","name":"Second"}),
        json!({"id":"3"}),
        json!({"name":"No id"}),
        json!({"id":"4","summary":"Last"}),
    ];
    let result = ua::embeddings::build_embeddings(&nodes, &fake, "test-model", 2).unwrap();
    assert_eq!(
        fake.calls.borrow().as_slice(),
        &[
            vec!["First\nDetail\ntag".to_string(), "Second".to_string()],
            vec!["Last".to_string()]
        ]
    );
    assert_eq!(result.dim, 2);
    assert_eq!(result.embeddings.len(), 3);
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("embeddings.json");
    ua::embeddings::save_embeddings(&path, &result).unwrap();
    assert_eq!(
        ua::embeddings::load_embeddings(&path).unwrap(),
        Some(result)
    );
    assert_eq!(
        ua::embeddings::load_embeddings(&tmp.path().join("absent")).unwrap(),
        None
    );
}
#[test]
fn vector_search_filters_missing_vectors_and_handles_zero_norm() {
    let nodes = vec![
        json!({"id":"a","type":"file"}),
        json!({"id":"b","type":"class"}),
        json!({"id":"missing","type":"file"}),
    ];
    let result: EmbeddingResult =
        serde_json::from_value(json!({"model":"x","dim":2,"embeddings":{"a":[1,0],"b":[0,0]}}))
            .unwrap();
    let mut search = ua::search::SemanticSearchEngine::new(nodes, result.embeddings);
    assert!(search.has_embeddings());
    let hits = search.search(&[1., 0.], 10, 0., &[]).unwrap();
    assert_eq!(hits.len(), 2);
    assert_eq!(hits[0].node_id, "a");
    assert_eq!(hits[0].score, 0.);
    assert_eq!(hits[1].score, 1.);
    assert!(
        search
            .search(&[1., 0.], 10, 0.1, &["class".into()])
            .unwrap()
            .is_empty()
    );
    search.add_embedding("missing".into(), vec![-1., 0.]);
    assert_eq!(search.search(&[1., 0.], 10, -1., &[]).unwrap().len(), 3);
    assert!(ua::search::cosine_similarity(&[1.], &[1., 2.]).is_err());
}
#[test]
fn schema_and_repair_boundaries_differ() {
    let graph = json!({"project":{"name":"Test","languages":[],"frameworks":[],"description":"test","analyzedAt":"","gitCommitHash":""},"nodes":[{"id":"x","name":"x","type":"FN","custom":{"retained":true}}],"edges":[],"layers":null});
    assert!(ua::schemas::validate("knowledge-graph", &graph).is_err());
    let repaired = ua::validation::validate_graph(&graph);
    assert_eq!(repaired["success"], true);
    assert_eq!(repaired["data"]["nodes"][0]["type"], "function");
    assert_eq!(repaired["data"]["nodes"][0]["custom"]["retained"], true);
}
#[test]
fn persistence_fallbacks_and_path_sanitization() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    assert_eq!(
        ua::persistence::load_config(root),
        json!({"autoUpdate":false})
    );
    ua::persistence::save_config(root, &json!({"splitDepth":2,"custom":{"x":1}})).unwrap();
    assert_eq!(ua::persistence::load_config(root)["custom"]["x"], 1);
    fs::write(root.join(".ua/config.json"), "{").unwrap();
    assert_eq!(
        ua::persistence::load_config(root),
        json!({"autoUpdate":false})
    );
    fs::write(root.join(".ua/fingerprints.json"), "{").unwrap();
    assert!(ua::persistence::load_fingerprints(root).is_none());
    let graph = json!({"nodes":[{"id":"1","filePath":root.join("src/x.rs")},{"id":"2","filePath":"/outside/y.rs"},{"id":"3","filePath":"relative/z.rs"}],"extension":"yes"});
    ua::persistence::save_graph(root, &graph).unwrap();
    let loaded = ua::persistence::load_graph(root, false).unwrap().unwrap();
    assert_eq!(loaded["nodes"][0]["filePath"], "src/x.rs");
    assert_eq!(loaded["nodes"][1]["filePath"], "y.rs");
    assert_eq!(loaded["nodes"][2]["filePath"], "relative/z.rs");
    assert_eq!(loaded["extension"], "yes");
}
#[test]
fn standalone_scan_without_runtime_tools() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("project");
    fs::create_dir_all(root.join("src")).unwrap();
    fs::create_dir_all(root.join("node_modules")).unwrap();
    fs::write(root.join("src/文.py"), "# hello\nx = 1\n").unwrap();
    fs::write(root.join("node_modules/no.py"), "skip\n").unwrap();
    fs::write(root.join("root.txt"), "a\nb").unwrap();
    let output = tmp.path().join("scan.json");
    let status = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args(["scan_project"])
        .arg(&root)
        .arg(&output)
        .env("PATH", "")
        .output()
        .unwrap();
    assert!(
        status.status.success(),
        "{}",
        String::from_utf8_lossy(&status.stderr)
    );
    assert!(status.stdout.is_empty());
    let scan = ua::persistence::read_json(&output).unwrap();
    assert_eq!(scan["totalFiles"], 2);
    assert_eq!(scan["files"][1]["path"], "src/文.py");
    assert_eq!(scan["files"][1]["sizeLines"], 2);
    assert_eq!(scan["files"][0]["sizeLines"], 1);
}
#[test]
fn invalid_commands_and_partition_arguments_do_not_write_artifacts() {
    let tmp = tempfile::tempdir().unwrap();
    let command = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .current_dir(tmp.path())
        .args(["scan_project"])
        .output()
        .unwrap();
    assert!(!command.status.success());
    assert!(command.stdout.is_empty());
    assert_eq!(fs::read_dir(tmp.path()).unwrap().count(), 0);
    assert!(ua::partition::partition_files(&["a.py".into()], &[], None).is_err());
    assert!(ua::partition::partition_files(&["a.py".into()], &[], Some(0)).is_err());
}
#[test]
fn pending_and_affected_parts_union() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    ua::persistence::save_config(
        root,
        &json!({"splitDepth":1,"includedParts":["src","tests","docs"]}),
    )
    .unwrap();
    fs::create_dir_all(root.join(".ua/partitions")).unwrap();
    for part in ["src", "tests"] {
        fs::write(
            root.join(".ua/partitions")
                .join(ua::partition::part_to_filename(part)),
            "{}",
        )
        .unwrap();
    }
    assert_eq!(
        ua::partition::parts_to_process(root, false, &["src/x.py".into(), "vendor/x.py".into()])
            .unwrap(),
        vec!["docs", "src"]
    );
    assert_eq!(
        ua::partition::parts_to_process(root, true, &[]).unwrap(),
        vec!["src", "tests", "docs"]
    );
}
#[test]
fn fingerprint_decisions_cover_directory_changes_and_boundaries() {
    let paths = (0..10).map(|i| format!("src/{i}.py")).collect();
    let new = ua::fingerprints::classify_update(
        &[json!({"filePath":"new/x.py","changeLevel":"STRUCTURAL","status":"new"})],
        &paths,
    );
    assert_eq!(new["action"], "ARCHITECTURE_UPDATE");
    let paths = ["src/a.py", "docs/readme.md", "tests/a.py"]
        .into_iter()
        .map(str::to_owned)
        .collect();
    let deleted = ua::fingerprints::classify_update(
        &[json!({"filePath":"src/a.py","changeLevel":"STRUCTURAL","status":"deleted"})],
        &paths,
    );
    assert_eq!(deleted["action"], "ARCHITECTURE_UPDATE");
    assert_eq!(
        ua::fingerprints::content_hash("hello"),
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    );
}
#[test]
fn topological_order_respects_dependencies() {
    let data = json!({"fileNodes":[{"id":"a","filePath":"app/a.py"},{"id":"b","filePath":"core/b.py"},{"id":"c","filePath":"lib/c.py"}],"importEdges":[{"source":"a","target":"b"},{"source":"b","target":"c"}]});
    let out = ua::analytics::analyze(&data).unwrap();
    assert_eq!(
        out["phase2Recommendations"]["topologicalOrder"],
        json!(["lib", "core", "app"])
    );
}
#[test]
#[ignore = "requires parser downloads; run explicitly with a cold or warmed cache"]
fn all_supported_parsers() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        ua::parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    for language in ua::parsers::LANGUAGES {
        let tree = ua::parsers::parse(language, "").unwrap_or_else(|e| panic!("{language}: {e}"));
        assert!(!tree.root_node().kind().is_empty());
    }
}
#[test]
fn merge_update_prunes_changed_nodes_and_edges_but_retains_metadata() {
    let graph = json!({"project":{"name":"sample","extension":1},"nodes":[{"id":"a","filePath":"a.py"},{"id":"b","filePath":"b.py"}],"edges":[{"source":"a","target":"b"}],"layers":[],"custom":{"saved":true}});
    let result = ua::staleness::merge_graph_update(
        &graph,
        &["a.py".into()],
        &[json!({"id":"new","filePath":"a.py"})],
        &[],
        "commit",
    );
    assert_eq!(result["nodes"][0]["id"], "b");
    assert_eq!(result["nodes"][1]["id"], "new");
    assert_eq!(result["edges"], json!([]));
    assert_eq!(result["custom"]["saved"], true);
    assert_eq!(result["project"]["extension"], 1);
    assert_eq!(result["project"]["gitCommitHash"], "commit");
}
#[test]
#[ignore = "requires local loopback binding"]
fn http_embedding_contract() {
    use std::io::{Read, Write};
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(5)))
            .unwrap();
        let mut request = vec![];
        let mut buffer = [0u8; 1024];
        loop {
            let n = stream.read(&mut buffer).unwrap();
            assert!(n > 0);
            request.extend_from_slice(&buffer[..n]);
            if let Some(split) = request.windows(4).position(|w| w == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&request[..split]).to_lowercase();
                let length = headers
                    .lines()
                    .find_map(|l| {
                        l.strip_prefix("content-length:")
                            .and_then(|s| s.trim().parse::<usize>().ok())
                    })
                    .unwrap();
                if request.len() >= split + 4 + length {
                    assert!(headers.starts_with("post /v1/embeddings http/1.1"));
                    assert!(headers.contains("authorization: bearer test-key"));
                    let body: serde_json::Value =
                        serde_json::from_slice(&request[split + 4..]).unwrap();
                    assert_eq!(
                        body,
                        json!({"model":"test-model","input":["first","second"]})
                    );
                    break;
                }
            }
        }
        let body =
            r#"{"data":[{"index":1,"embedding":[2.0,3.0]},{"index":0,"embedding":[0.0,1.0]}]}"#;
        write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
    });
    let client = ua::embeddings::HttpEmbeddingClient::new(
        "test-key".into(),
        "test-model".into(),
        format!("http://{address}/v1/"),
    )
    .unwrap();
    assert_eq!(
        client.embed(&["first".into(), "second".into()]).unwrap(),
        vec![vec![0., 1.], vec![2., 3.]]
    );
    server.join().unwrap();
}
#[test]
fn louvain_batches_are_repeatable_complete_bounded_and_keep_neighbor_links() {
    use std::collections::{BTreeMap, BTreeSet};
    let tmp = tempfile::tempdir().unwrap();
    let files: Vec<_> = (0..82)
        .map(|i| {
            let p = format!("f{i:03}.unknown");
            fs::write(tmp.path().join(&p), "").unwrap();
            json!({"path":p,"language":"unknown","fileCategory":"code"})
        })
        .collect();
    let mut imports = json!({});
    // A large clique forces community splitting; disconnected singletons pool.
    for i in 0..80 {
        imports[format!("f{i:03}.unknown")] = json!(
            (0..80)
                .filter(|j| *j != i)
                .map(|j| format!("f{j:03}.unknown"))
                .collect::<Vec<_>>()
        );
    }
    let scan = json!({"files":files,"importMap":imports});
    let one = ua::batching::compute_batches(tmp.path(), &scan, None);
    let two = ua::batching::compute_batches(tmp.path(), &scan, None);
    assert_eq!(one, two);
    let mut assignment = BTreeMap::new();
    for b in ua::array(&one, "batches") {
        assert!(ua::array(b, "files").len() <= 35);
        for f in ua::array(b, "files") {
            assert!(
                assignment
                    .insert(f["path"].as_str().unwrap(), b["batchIndex"].clone())
                    .is_none()
            );
        }
    }
    assert_eq!(assignment.len(), 82);
    for b in ua::array(&one, "batches") {
        for (path, neighbors) in b["neighborMap"].as_object().unwrap() {
            assert!(neighbors.as_array().unwrap().len() <= 50);
            for n in neighbors.as_array().unwrap() {
                assert_eq!(n["batchIndex"], assignment[n["path"].as_str().unwrap()]);
                assert_ne!(n["batchIndex"], assignment[path.as_str()]);
            }
        }
    }
    let changed = BTreeSet::from(["f000.unknown".to_owned()]);
    let filtered = ua::batching::compute_batches(tmp.path(), &scan, Some(&changed));
    assert_eq!(ua::array(&filtered, "batches").len(), 1);
    let b = &filtered["batches"][0];
    assert_eq!(b["batchIndex"], assignment["f000.unknown"]);
    assert_eq!(ua::array(b, "files").len(), 1);
    assert_eq!(b["files"][0]["path"], "f000.unknown");
    assert_eq!(b["batchImportData"].as_object().unwrap().len(), 1);
    assert_eq!(b["batchImportData"]["f000.unknown"], scan["importMap"]["f000.unknown"]);
    let neighbors = b["neighborMap"]["f000.unknown"].as_array().unwrap();
    assert!(!neighbors.is_empty() && neighbors.len() <= 50);
    for neighbor in neighbors {
        let path = neighbor["path"].as_str().unwrap();
        assert_ne!(path, "f000.unknown");
        assert_eq!(neighbor["batchIndex"], assignment[path]);
    }
}
#[test]
fn corrupt_interrupted_and_wrong_version_parser_caches_fail_explicitly() {
    for scenario in ["corrupt", "interrupted", "wrong-version"] {
        let tmp = tempfile::tempdir().unwrap();
        let version = if scenario == "wrong-version" {
            "v0.0.0"
        } else {
            "v1.20.0"
        };
        let dir = tmp
            .path()
            .join(format!("tree-sitter-language-pack/{version}/libs"));
        fs::create_dir_all(&dir).unwrap();
        let ext = if cfg!(target_os = "macos") {
            "dylib"
        } else {
            "so"
        };
        let suffix = if scenario == "interrupted" {
            ".partial"
        } else {
            ""
        };
        let bad = dir.join(format!("libtree_sitter_python.{ext}{suffix}"));
        fs::write(&bad, b"incomplete download").unwrap();
        let result = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .args(["--parser-cache-dir"])
            .arg(tmp.path())
            .args(["parsers", "fetch", "python"])
            .env(
                "TREE_SITTER_LANGUAGE_PACK_MANIFEST_URL",
                "file:///nonexistent-ua-parser-manifest.json",
            )
            .env("HTTP_PROXY", "http://127.0.0.1:1")
            .env("HTTPS_PROXY", "http://127.0.0.1:1")
            .output()
            .unwrap();
        assert!(!result.status.success(), "{scenario}");
        assert!(result.stdout.is_empty());
        assert!(!result.stderr.is_empty());
        if scenario == "wrong-version" {
            assert_eq!(fs::read(&bad).unwrap(), b"incomplete download");
        }
    }
}

#[test]
fn fingerprint_guard_preserves_unreadable_existing_store() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("fingerprints.json");
    fs::write(&path, "{").unwrap();
    assert!(
        ua::fingerprints::patch_and_save_fingerprints(&path, temp.path(), &[], Some("abc"))
            .is_err()
    );
    assert_eq!(fs::read_to_string(&path).unwrap(), "{");
    let store = json!({"files":{"missing.py":{"contentHash":"kept"}},"gitCommitHash":"old"});
    fs::write(&path, store.to_string()).unwrap();
    let counts = ua::fingerprints::patch_and_save_fingerprints(
        &path,
        temp.path(),
        &["missing.py".into()],
        Some("new"),
    )
    .unwrap();
    assert_eq!(counts, (1, 0));
    assert_eq!(
        ua::persistence::read_json(&path).unwrap()["gitCommitHash"],
        "new"
    );
}
#[test]
fn validated_records_keep_extensions_and_apply_boundary_defaults() {
    let meta=ua::models::AnalysisMeta::from_value(json!({"lastAnalyzedAt":"now","gitCommitHash":"abc","version":"1","analyzedFiles":"42","extension":{"nullable":null}})).unwrap();
    assert_eq!(meta["analyzedFiles"], 42);
    assert_eq!(meta.without_nulls()["extension"], json!({"nullable":null}));
    assert!(meta.without_nulls().get("theme").is_none());
    let config = ua::models::ProjectConfig::from_value(json!({})).unwrap();
    assert_eq!(config["includedParts"], json!([]));
    assert_eq!(config["autoUpdate"], false);
    assert!(ua::models::ScanFile::from_value(json!({"path":"x","language":"python","fileCategory":"code","sizeLines":1,"future":true})).is_err());
    let input =
        ua::models::StructureBatchFile::from_value(json!({"path":"x","future":true})).unwrap();
    assert!(input.get("future").is_none());
}
#[test]
fn path_sanitization_matches_lexical_prefix_contract() {
    let graph = json!({"nodes":[{"filePath":"/tmp/project-other/a.py"},{"filePath":"/tmp/project"},{"filePath":"/tmp/outside/a.py"},{"filePath":"文/a.py"}]});
    let actual = ua::persistence::sanitize_file_paths(&graph, std::path::Path::new("/tmp/project"));
    assert_eq!(actual["nodes"][0]["filePath"], "../project-other/a.py");
    assert_eq!(actual["nodes"][1]["filePath"], ".");
    assert_eq!(actual["nodes"][2]["filePath"], "a.py");
    assert_eq!(actual["nodes"][3]["filePath"], "文/a.py");
}

#[test]
fn part_merge_preserves_boundary_edges_and_recovers_imports() {
    for emitted in [true, false] {
        let tmp = tempfile::tempdir().unwrap();
        let inter = tmp.path().join(".understand-anything/intermediate");
        fs::create_dir_all(&inter).unwrap();
        let scan = json!({"files":[{"path":"a/one.ts"},{"path":"b/two.ts"}],
            "importMap":{"a/one.ts":["b/two.ts"],"b/two.ts":["a/one.ts"]}});
        ua::persistence::write_json(&inter.join("scan-result.json"), &scan).unwrap();
        let edges = if emitted {
            vec![
                json!({"source":"file:a/one.ts","target":"file:b/two.ts","type":"imports"}),
                json!({"source":"file:a/one.ts","target":"file:missing.ts","type":"imports"}),
            ]
        } else {
            vec![]
        };
        ua::persistence::write_json(
            &inter.join("batch-0.json"),
            &json!({
            "nodes":[{"id":"file:a/one.ts","type":"file","filePath":"a/one.ts"}],"edges":edges}),
        )
        .unwrap();
        let graph = ua::batch_merge::merge_batch_directory(tmp.path()).unwrap();
        assert_eq!(ua::array(&graph, "edges").len(), 1);
        let part = ua::assembly::build_part_graph(
            &graph,
            "a",
            &["a/one.ts".into(), "b/two.ts".into()].into(),
            &scan,
            "",
        );
        assert_eq!(
            ua::array(&part, "nodes")
                .iter()
                .filter(|n| n["stub"] == true)
                .count(),
            1
        );
        assert_eq!(part["edges"][0]["target"], "file:b/two.ts");
        let (merged, _) = ua::merge::merge_graphs(&[
            part,
            json!({"nodes":[{"id":"file:b/two.ts","type":"file","summary":"Real node"}],"edges":[]}),
        ]);
        assert!(
            ua::array(&merged, "nodes")
                .iter()
                .all(|n| n["stub"] != true)
        );
        assert_eq!(ua::array(&merged, "edges").len(), 1);
    }
}

#[test]
fn deleted_part_runs_through_empty_batch_assembly() {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path();
    let inter = root.join(".understand-anything/intermediate");
    fs::create_dir_all(&inter).unwrap();
    ua::persistence::write_json(
        &root.join(".understand-anything/config.json"),
        &json!({"includedParts":["deleted"],"splitDepth":1}),
    )
    .unwrap();
    ua::persistence::write_json(
        &inter.join("scan-result.json"),
        &json!({"files":[],"importMap":{}}),
    )
    .unwrap();
    let saved = root.join(".understand-anything/partitions/deleted.knowledge-graph.json");
    fs::create_dir_all(saved.parent().unwrap()).unwrap();
    ua::persistence::write_json(
        &saved,
        &json!({"nodes":[{"id":"file:deleted/last.txt"}],"edges":[]}),
    )
    .unwrap();
    let run = |args: &[&str]| {
        let result = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .args(args)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        String::from_utf8(result.stdout).unwrap()
    };
    let root_str = root.to_str().unwrap();
    run(&["partition_files", root_str, "--depth=1"]);
    let list = inter.join("part-files/deleted.json");
    assert_eq!(serde_json::from_str::<serde_json::Value>(&fs::read_to_string(&list).unwrap()).unwrap(), json!([]));
    fs::write(root.join("changed.txt"), "deleted/last.txt\n").unwrap();
    let selection = run(&[
        "parts_to_process",
        root_str,
        &format!("--changed={}", root.join("changed.txt").display()),
    ]);
    assert_eq!(selection.trim(), "deleted");
    run(&[
        "compute_batches",
        root_str,
        &format!("--changed-files={}", list.display()),
    ]);
    run(&["merge_batch_graphs", root_str]);
    run(&["assemble_part_graph", root_str, "deleted"]);
    let graph = ua::persistence::read_json(&saved).unwrap();
    assert!(ua::array(&graph, "nodes").is_empty());
    assert!(ua::array(&graph, "edges").is_empty());
}
