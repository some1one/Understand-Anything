use serde_json::{Map, json};
use understand_anything::batch_merge::{is_test_path, link_tests};

#[test]
fn language_test_conventions_do_not_confuse_production_or_helpers() {
    for path in [
        "Sources/AppTests.swift",
        "Tests/App/Support.swift",
        "src/parser_test.rs",
        "tests/parser.rs",
        "test_parser.rs",
        "spec/user_spec.rb",
        "spec/spec_helper.rb",
        "test_user.rb",
        "tests/Feature/User.php",
        "src/UserTest.php",
        "AppSpec.scala",
        "AppSuite.scala",
        "Tests/Support.SWIFT",
    ] {
        assert!(is_test_path(path), "{path}");
    }
    for path in [
        "Contest.swift",
        "src/contest.rs",
        "lib/latest.rb",
        "src/Contest.php",
        "__tests__/helpers.ts",
        "tests/helpers.js",
        "src/Tests.php",
    ] {
        assert!(!is_test_path(path), "{path}");
    }
}

#[test]
fn explicit_test_edges_survive_and_reverse_edges_are_corrected() {
    for (production, test) in [
        ("App.swift", "Tests/AppTests.swift"),
        ("src/parser.rs", "tests/parser.rs"),
        ("lib/user.rb", "spec/user_spec.rb"),
        ("src/User.php", "tests/Feature/User.php"),
    ] {
        for reverse in [false, true] {
            let prod_id = format!("file:{production}");
            let test_id = format!("file:{test}");
            let mut nodes = Map::new();
            for (id, path) in [(&prod_id, production), (&test_id, test)] {
                nodes.insert(
                    id.clone(),
                    json!({"id":id,"type":"file","filePath":path,"tags":[]}),
                );
            }
            let (source, target) = if reverse {
                (&test_id, &prod_id)
            } else {
                (&prod_id, &test_id)
            };
            let mut edges =
                vec![json!({"source":source,"target":target,"type":"tested_by","weight":0.8})];
            link_tests(&mut nodes, &mut edges);
            assert_eq!(edges.len(), 1, "{test}");
            assert_eq!(edges[0]["source"], prod_id);
            assert_eq!(edges[0]["target"], test_id);
            assert_eq!(edges[0]["weight"], 0.8);
            assert!(
                nodes[&prod_id]["tags"]
                    .as_array()
                    .unwrap()
                    .contains(&json!("tested"))
            );
        }
    }
}
