use serde_json::{Value, json};
use std::{collections::BTreeSet, fs, path::Path, process::Command};
use understand_anything as ua;
fn equal(actual: &Value, expected: &Value, path: &str) {
    match (actual, expected) {
        (Value::Number(a), Value::Number(b)) => assert!(
            (a.as_f64().unwrap() - b.as_f64().unwrap()).abs() <= 1e-9,
            "{path}: {a} != {b}"
        ),
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{path}: {a:?} != {b:?}");
            for (i, (a, b)) in a.iter().zip(b).enumerate() {
                equal(a, b, &format!("{path}/{i}"));
            }
        }
        (Value::Object(a), Value::Object(b)) => {
            assert_eq!(a.len(), b.len(), "{path}: {a:?} != {b:?}");
            for (k, v) in b {
                equal(
                    a.get(k).unwrap_or_else(|| panic!("{path}: missing {k}")),
                    v,
                    &format!("{path}/{k}"),
                );
            }
        }
        _ => assert_eq!(actual, expected, "{path}"),
    }
}
fn run(case: &Value) -> Value {
    let i = &case["input"];
    let s = |key: &str| i[key].as_str().unwrap_or("");
    match case["function"].as_str().unwrap() {
        "partition" => json!(
            ua::partition::partition_files(
                &ua::strings(&i["paths"]),
                &ua::strings(&i["sources"]),
                i["depth"].as_u64().map(|n| n as usize)
            )
            .unwrap()
        ),
        "layout" => ua::partition::detect_layout(&ua::strings(&i["paths"])),
        "detection" => {
            json!({"language":ua::scan::detect_language(s("path")),"category":ua::scan::detect_category(s("path")),"registry":ua::parsers::detect_registry_language(s("path"))})
        }
        "ignore" => json!(
            ua::scan::IgnoreFilter::new(&ua::strings(&i["patterns"]))
                .unwrap()
                .is_ignored(s("path"))
        ),
        "noncode" => ua::noncode::analyze(s("language"), s("content")).unwrap(),
        "fuzz" => json!([
            ua::search::partial_ratio(s("a"), s("b")),
            ua::search::token_set_ratio(s("a"), s("b"))
        ]),
        "search" => json!(
            ua::search::SearchEngine::new(i["nodes"].as_array().unwrap().clone()).search(
                s("query"),
                &ua::strings(&i["types"]),
                50
            )
        ),
        "cosine" => json!(
            ua::search::cosine_similarity(
                &serde_json::from_value::<Vec<f64>>(i["a"].clone()).unwrap(),
                &serde_json::from_value::<Vec<f64>>(i["b"].clone()).unwrap()
            )
            .unwrap()
        ),
        "validate" => ua::validation::validate_graph(&i["graph"]),
        "merge" => {
            let (graph, report) = ua::merge::merge_graphs(i["graphs"].as_array().unwrap());
            json!({"graph":graph,"report":report})
        }
        "stubs" => ua::merge::add_boundary_stubs(
            &i["graph"],
            &ua::strings(&i["known"])
                .into_iter()
                .collect::<BTreeSet<_>>(),
        ),
        "compare_fingerprints" => {
            json!(ua::fingerprints::compare_fingerprints(&i["old"], &i["new"]))
        }
        "classify_update" => ua::fingerprints::classify_update(
            i["changes"].as_array().unwrap(),
            &ua::strings(&i["paths"]).into_iter().collect(),
        ),
        unknown => panic!("unknown fixture function {unknown}"),
    }
}
#[test]
fn captured_python_api_cases() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/reference.json")).unwrap();
    for (index, case) in cases.iter().enumerate() {
        equal(
            &run(case),
            &case["expected"],
            &format!("case {index} ({})", case["function"]),
        );
    }
}
fn populate(root: &Path, files: &Value) {
    for (path, data) in files.as_object().unwrap() {
        let path = root.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(
            path,
            data.as_str()
                .unwrap()
                .replace("<ROOT>", &root.to_string_lossy()),
        )
        .unwrap();
    }
}
#[test]
fn captured_python_command_contracts() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/commands.json")).unwrap();
    let mut cases = cases;
    cases.extend(
        serde_json::from_str::<Vec<Value>>(include_str!("fixtures/review_commands.json")).unwrap(),
    );
    cases.extend(
        serde_json::from_str::<Vec<Value>>(include_str!("fixtures/pipeline_commands.json"))
            .unwrap(),
    );
    check_command_cases(cases);
}
fn check_command_cases(cases: Vec<Value>) {
    for case in cases {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path();
        populate(root, &case["before"]);
        let args: Vec<_> = ua::strings(&case["args"])
            .into_iter()
            .map(|s| s.replace("<ROOT>", &root.to_string_lossy()))
            .collect();
        let parser_args: Vec<String> = std::env::var("UA_TEST_PARSER_CACHE")
            .ok()
            .map(|s| vec!["--parser-cache-dir".into(), s])
            .unwrap_or_default();
        let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
            .args(parser_args)
            .arg(case["command"].as_str().unwrap())
            .args(args)
            .envs(
                case["env"]
                    .as_object()
                    .into_iter()
                    .flatten()
                    .map(|(k, v)| (k, v.as_str().unwrap())),
            )
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(case["status"].as_i64().unwrap() as i32),
            "{case:?}"
        );
        let clean =
            |bytes: &[u8]| String::from_utf8_lossy(bytes).replace(root.to_str().unwrap(), "<ROOT>");
        assert_eq!(
            clean(&output.stdout),
            case["stdout"].as_str().unwrap(),
            "{} stdout",
            case["command"]
        );
        assert_eq!(
            clean(&output.stderr),
            case["stderr"].as_str().unwrap(),
            "{} stderr",
            case["command"]
        );
        let mut actual = serde_json::Map::new();
        for entry in walkdir::WalkDir::new(root)
            .into_iter()
            .flatten()
            .filter(|e| e.file_type().is_file())
        {
            let rel = entry.path().strip_prefix(root).unwrap().to_str().unwrap();
            let content = fs::read_to_string(entry.path())
                .unwrap()
                .replace(root.to_str().unwrap(), "<ROOT>");
            actual.insert(rel.into(), json!(content));
        }
        for (path, expected) in case["after"].as_object().unwrap() {
            let content = actual.get(path).unwrap_or_else(|| panic!("missing {path}"));
            if path.ends_with(".json") {
                let mut a: Value = serde_json::from_str(content.as_str().unwrap()).unwrap();
                let mut b: Value = serde_json::from_str(expected.as_str().unwrap()).unwrap();
                normalize_dynamic(&mut a, root);
                normalize_dynamic(&mut b, root);
                equal(&a, &b, path);
            } else {
                assert_eq!(content, expected);
            }
        }
        assert_eq!(actual.len(), case["after"].as_object().unwrap().len());
    }
}
#[test]
#[ignore = "requires supported parser grammars for command parity"]
fn captured_remaining_command_contracts() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/additional_commands.json")).unwrap();
    check_command_cases(cases);
}
#[test]
fn captured_reviews_and_batch_boundaries() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/review_batches.json")).unwrap();
    for (index, case) in cases.iter().enumerate() {
        let i = &case["input"];
        let actual = match case["function"].as_str().unwrap() {
            "review" => {
                let mut review = ua::strict_validation::review_graph(
                    &i["graph"],
                    i["layers"].as_bool().unwrap(),
                );
                if i["scan"].is_array() {
                    ua::strict_validation::add_scan_coverage(
                        &mut review,
                        &i["graph"],
                        &ua::strings(&i["scan"]),
                    );
                }
                review
            }
            "noncode_batches" => json!(ua::batching::build_non_code_batches(
                i["files"].as_array().unwrap()
            )),
            "merge_small" => json!(ua::batching::merge_small_batches(
                i["batches"].as_array().unwrap()
            )),
            "count_assignment" => json!(ua::batching::count_based_assignment(
                i["files"].as_array().unwrap(),
                12
            )),
            _ => panic!("unknown fixture"),
        };
        equal(
            &actual,
            &case["expected"],
            &format!("review/batching {index}"),
        );
    }
}
#[test]
fn schema_exports_are_byte_exact() {
    let tmp = tempfile::tempdir().unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
        .args(["json_schema", "--output-dir"])
        .arg(tmp.path())
        .output()
        .unwrap();
    assert!(output.status.success());
    for (name, raw) in ua::schemas::SCHEMAS {
        assert_eq!(fs::read_to_string(tmp.path().join(name)).unwrap(), *raw);
    }
}
fn drop_null_fields(v: &mut Value) {
    match v {
        Value::Object(m) => {
            m.retain(|_, v| !v.is_null());
            for v in m.values_mut() {
                drop_null_fields(v);
            }
        }
        Value::Array(a) => {
            for v in a {
                drop_null_fields(v);
            }
        }
        _ => {}
    }
}
#[test]
fn captured_skill_prompts() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/skills.json")).unwrap();
    for c in cases {
        let i = &c["input"];
        let g = &i["graph"];
        match c["function"].as_str().unwrap() {
            "explain" => {
                let mut ctx = ua::skills::build_explain_context(g, i["path"].as_str().unwrap());
                assert_eq!(
                    ua::skills::format_explain_prompt(&ctx),
                    c["prompt"].as_str().unwrap()
                );
                drop_null_fields(&mut ctx);
                equal(&ctx, &c["context"], "explain");
            }
            "diff" => {
                let mut ctx = ua::skills::build_diff_context(g, &ua::strings(&i["changed"]));
                assert_eq!(
                    ua::skills::format_diff_analysis(&ctx),
                    c["prompt"].as_str().unwrap()
                );
                drop_null_fields(&mut ctx);
                equal(&ctx, &c["context"], "diff");
            }
            "onboard" => assert_eq!(
                ua::skills::build_onboarding_guide(g),
                c["prompt"].as_str().unwrap()
            ),
            "chat" => {
                let mut ctx = ua::skills::build_chat_context(g, i["query"].as_str().unwrap(), 15);
                let mut expected = c["context"].clone();
                drop_null_fields(&mut ctx);
                for value in [&mut ctx, &mut expected] {
                    value["relevantNodes"]
                        .as_array_mut()
                        .unwrap()
                        .sort_by_key(|n| n["id"].as_str().unwrap().to_owned());
                }
                equal(&ctx, &expected, "chat");
                assert_eq!(
                    ua::skills::format_context_for_prompt(&c["context"]),
                    c["prompt"].as_str().unwrap()
                );
            }
            _ => unreachable!(),
        }
    }
}
#[test]
fn captured_analytics() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/analytics.json")).unwrap();
    for (index, c) in cases.iter().enumerate() {
        let mut actual = ua::analytics::analyze(&c["input"]).unwrap();
        let mut expected = c["expected"].clone();
        for value in [&mut actual, &mut expected] {
            value["phase2Recommendations"]["topologicalOrder"]
                .as_array_mut()
                .unwrap()
                .sort_by_key(Value::to_string);
            value["dependencyDirection"]
                .as_array_mut()
                .unwrap()
                .sort_by_key(Value::to_string);
        }
        equal(&actual, &expected, &format!("analytics {index}"));
    }
}
#[test]
fn captured_pipeline_primitives() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/pipeline.json")).unwrap();
    for (index, c) in cases.iter().enumerate() {
        let i = &c["input"];
        let actual = match c["function"].as_str().unwrap() {
            "file_graph" => {
                let path = i["path"].as_str().unwrap();
                let category = i["category"].as_str();
                json!({"node":ua::file_graph::file_level_node(category,path),"tags":ua::file_graph::deterministic_tags(category,path),"test":ua::file_graph::is_test_file(path)})
            }
            "seed" => ua::seed::build_seed(&i["context"], &i["results"]),
            "draft" => json!(ua::batch_validation::validate_draft(
                &i["context"],
                &i["seed"],
                &i["draft"]
            )),
            "split" => json!(ua::batch_validation::split_into_parts(
                i["nodes"].as_array().unwrap(),
                i["edges"].as_array().unwrap(),
                &ua::strings(&i["files"])
            )),
            "structure_check" => json!(ua::batch_validation::check_structure_output(
                &i["context"],
                &i["results"]
            )),
            "batch_payloads" => json!(ua::seed::build_batch_payloads(
                i["root"].as_str().unwrap(),
                &i["batch"]
            )),
            _ => unreachable!(),
        };
        equal(&actual, &c["expected"], &format!("pipeline {index}"));
    }
}
#[test]
#[ignore = "requires the supported parser grammars; run with UA_TEST_PARSER_CACHE"]
fn captured_structural_extraction() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        ua::parsers::configure(Some(Path::new(&cache))).unwrap();
    }
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/structure.json")).unwrap();
    for (index, c) in cases.iter().enumerate() {
        let path = c["path"].as_str().unwrap();
        let source = c["source"].as_str().unwrap();
        let a = ua::structure::analyze_file(path, source);
        let calls = ua::structure::extract_call_graph(path, source);
        equal(
            &json!(a),
            &c["analysis"],
            &format!("structure {index}: {path}"),
        );
        equal(
            &json!(calls),
            &c["calls"],
            &format!("calls {index}: {path}"),
        );
        let (total, nonempty) = ua::structure::count_lines(source);
        let file = json!({"path":path,"language":null,"fileCategory":"code"});
        equal(
            &ua::structure::build_result(
                &file,
                total,
                nonempty,
                a.as_ref(),
                calls.as_deref(),
                &json!({path:[]}),
            ),
            &c["result"],
            &format!("build_result {index}"),
        );
    }
}
#[test]
#[ignore = "requires parser grammars; run with UA_TEST_PARSER_CACHE"]
fn captured_import_resolution() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        ua::parsers::configure(Some(Path::new(&cache))).unwrap();
    }
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/imports.json")).unwrap();
    for (index, c) in cases.iter().enumerate() {
        let tmp = tempfile::tempdir().unwrap();
        populate(tmp.path(), &c["files"]);
        let mut input = c["input"].clone();
        input["projectRoot"] = json!(tmp.path());
        equal(
            &ua::imports::extract_import_map(&input).unwrap(),
            &c["expected"],
            &format!("imports {index}"),
        );
    }
}
#[test]
fn captured_merge_normalization_and_test_linking() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/merging.json")).unwrap();
    for (index, c) in cases.iter().enumerate() {
        let a = c["args"].as_array().unwrap();
        let actual = match c["function"].as_str().unwrap() {
            "merge_and_normalize" => json!(ua::batch_merge::merge_and_normalize(
                a[0].as_array().unwrap()
            )),
            "normalize_node_id" => json!(ua::batch_merge::normalize_node_id(
                a[0].as_str().unwrap(),
                &a[1]
            )),
            "normalize_complexity" => json!(ua::batch_merge::normalize_complexity(&a[0])),
            "classify_id_fix" => json!(ua::batch_merge::classify_id_fix(
                a[0].as_str().unwrap(),
                a[1].as_str().unwrap()
            )),
            "is_test_path" => json!(ua::batch_merge::is_test_path(a[0].as_str().unwrap())),
            "production_candidates" => json!(ua::batch_merge::production_candidates(
                a[0].as_str().unwrap()
            )),
            "normalize_direction" => json!(ua::batch_merge::normalize_direction(&a[0])),
            "link_tests" => {
                let mut nodes = a[0].as_object().unwrap().clone();
                let mut edges = a[1].as_array().unwrap().clone();
                let out = ua::batch_merge::link_tests(&mut nodes, &mut edges);
                equal(
                    &json!(nodes),
                    &c["after"][0],
                    &format!("link nodes {index}"),
                );
                equal(
                    &json!(edges),
                    &c["after"][1],
                    &format!("link edges {index}"),
                );
                json!(out)
            }
            _ => panic!("unknown fixture"),
        };
        equal(
            &actual,
            &c["expected"],
            &format!("merge {index}: {}", c["function"]),
        );
    }
}
fn normalize_dynamic(value: &mut Value, root: &Path) {
    match value {
        Value::Object(o) => {
            for (k, v) in o {
                if ["lastAnalyzedAt", "generatedAt", "analyzedAt"].contains(&k.as_str()) {
                    *v = json!("<TIME>");
                } else {
                    normalize_dynamic(v, root);
                }
            }
        }
        Value::Array(a) => {
            for v in a {
                normalize_dynamic(v, root);
            }
        }
        Value::String(s) => *s = s.replace(root.to_str().unwrap(), "<ROOT>"),
        _ => {}
    }
}
#[test]
#[ignore = "requires Python grammar; run with UA_TEST_PARSER_CACHE"]
fn captured_incremental_updates() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        ua::parsers::configure(Some(Path::new(&cache))).unwrap();
    }
    struct Git {
        head: Option<String>,
        changed: Option<Vec<String>>,
    }
    impl ua::updates::GitClient for Git {
        fn head(&self, _: &Path) -> Option<String> {
            self.head.clone()
        }
        fn changed_files(&self, _: &Path, _: &str, _: &str) -> Option<Vec<String>> {
            self.changed.clone()
        }
    }
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/updates.json")).unwrap();
    for (index, c) in cases.iter().enumerate() {
        let tmp = tempfile::tempdir().unwrap();
        let root = tmp.path();
        populate(root, &c["before"]);
        let git = Git {
            head: c["git"]["head"].as_str().map(str::to_owned),
            changed: if c["git"]["changed"].is_array() {
                Some(ua::strings(&c["git"]["changed"]))
            } else {
                None
            },
        };
        let result = match c["function"].as_str().unwrap() {
            "preflight" => {
                ua::updates::preflight_with_git(root, c["force"].as_bool().unwrap_or(false), &git)
            }
            "fingerprint_check" => ua::updates::fingerprint_check(root),
            "apply_batches" => ua::updates::apply_batches(root),
            "finalize" => ua::updates::finalize(root),
            _ => panic!("unknown phase"),
        };
        if let Some(error) = c["error"].as_str() {
            assert_eq!(result.unwrap_err().to_string(), error);
        } else {
            let mut actual = result.unwrap();
            normalize_dynamic(&mut actual, root);
            equal(&actual, &c["expected"], &format!("update {index}"));
        }
        let paths: Vec<_> = walkdir::WalkDir::new(root)
            .into_iter()
            .flatten()
            .filter(|e| e.file_type().is_file())
            .collect();
        assert_eq!(
            paths.len(),
            c["after"].as_object().unwrap().len(),
            "update {index} artifact count"
        );
        for (path, expected) in c["after"].as_object().unwrap() {
            let actual = fs::read_to_string(root.join(path)).unwrap();
            if path.ends_with(".json") {
                let mut actual: Value = serde_json::from_str(&actual).unwrap();
                normalize_dynamic(&mut actual, root);
                equal(
                    &actual,
                    &serde_json::from_str(expected.as_str().unwrap()).unwrap(),
                    &format!("update {index}: {path}"),
                );
            } else {
                assert_eq!(
                    actual.replace(root.to_str().unwrap(), "<ROOT>"),
                    expected.as_str().unwrap()
                );
            }
        }
    }
}

#[test]
fn captured_repair_validation() {
    let cases: Value = serde_json::from_str(include_str!("fixtures/validation.json")).unwrap();
    for (index, case) in cases.as_array().unwrap().iter().enumerate() {
        let input = &case["args"][0];
        let actual = match case["function"].as_str().unwrap() {
            "validate_graph" => ua::validation::validate_graph(input),
            "sanitize_graph" => ua::validation::sanitize_graph(input),
            "normalize_graph" => ua::validation::normalize_graph(input),
            "auto_fix_graph" => json!(ua::validation::auto_fix_graph(input)),
            _ => unreachable!(),
        };
        equal(
            &actual,
            &case["expected"],
            &format!("repair case {index}: {}", case["function"]),
        );
    }
}
#[test]
fn captured_strict_schema_diagnostics() {
    let cases: Value = serde_json::from_str(include_str!("fixtures/strict_schemas.json")).unwrap();
    for (index, case) in cases.as_array().unwrap().iter().enumerate() {
        let actual = ua::schemas::validate(case["schema"].as_str().unwrap(), &case["input"])
            .err()
            .map(|e| e.to_string());
        equal(
            &json!(actual),
            &case["expected"],
            &format!("schema case {index}: {}", case["schema"]),
        );
    }
}

#[test]
fn captured_model_defaults_and_coercions() {
    let cases: Value = serde_json::from_str(include_str!("fixtures/models.json")).unwrap();
    for (index, case) in cases.as_array().unwrap().iter().enumerate() {
        let result = ua::models::validate_model(case["model"].as_str().unwrap(), &case["input"]);
        let actual = match result {
            Ok(output) => {
                json!({"valid":true,"withoutNulls":ua::models::exclude_model_none(case["model"].as_str().unwrap(),&output),"output":output})
            }
            Err(_) => json!({"valid":false}),
        };
        equal(
            &actual,
            &case["expected"],
            &format!(
                "model case {index}: {} input={}",
                case["model"], case["input"]
            ),
        );
    }
}

#[test]
fn captured_parser_and_scorer_edges() {
    let cases: Value = serde_json::from_str(include_str!("fixtures/parser_edges.json")).unwrap();
    for (i, case) in cases.as_array().unwrap().iter().enumerate() {
        equal(
            &run(case),
            &case["expected"],
            &format!("parser edge {i}: {}", case["input"]),
        );
    }
}

#[test]
fn captured_command_argument_statuses() {
    let cases: Vec<Value> = serde_json::from_str(include_str!("fixtures/statuses.json")).unwrap();
    for case in cases {
        for name in std::iter::once(case["command"].as_str().unwrap().to_owned())
            .chain(ua::strings(&case["aliases"]))
        {
            let root = tempfile::tempdir().unwrap();
            fs::create_dir(root.path().join("root")).unwrap();
            let output = Command::new(env!("CARGO_BIN_EXE_understand-anything-rs"))
                .arg(&name)
                .args(ua::strings(&case["args"]))
                .current_dir(root.path())
                .env("UNDERSTAND_EMBEDDINGS_API_KEY", "")
                .output()
                .unwrap();
            assert_eq!(
                output.status.code(),
                Some(case["status"].as_i64().unwrap() as i32),
                "{name} {} stderr={}",
                case["args"],
                String::from_utf8_lossy(&output.stderr)
            );
        }
    }
}
