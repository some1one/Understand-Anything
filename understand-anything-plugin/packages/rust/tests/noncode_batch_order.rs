use serde_json::{Value, json};
use understand_anything::batching::build_non_code_batches;

#[test]
fn reserved_groups_preserve_distinct_ordering_and_duplicate_payload_rules() {
    let paths = ["z/docker-compose.yml", "z/Dockerfile", "a/Dockerfile", "z/.dockerignore",
        "db/migrations/002.sql", "db/migrations/001.sql", "db/migrations/notes.md",
        ".github/workflows/z.yml", ".github/workflows/a.yml", "a/readme.md", "z/Dockerfile"];
    let files: Vec<_> = paths.iter().enumerate().map(|(i, path)| json!({"path":path,"marker":i})).collect();
    let groups = build_non_code_batches(&files);
    let grouped: Vec<Vec<_>> = groups.iter().map(|group| group["files"].as_array().unwrap().iter().map(|f| f["path"].as_str().unwrap()).collect()).collect();
    assert_eq!(grouped, vec![
        vec!["a/Dockerfile"],
        vec!["z/docker-compose.yml", "z/Dockerfile", "z/.dockerignore"],
        vec![".github/workflows/z.yml", ".github/workflows/a.yml"],
        vec!["db/migrations/001.sql", "db/migrations/002.sql"],
        vec!["a/readme.md"], vec!["db/migrations/notes.md"],
    ]);
    assert_eq!(groups[1]["files"][1]["marker"], 10);
    let flags: Vec<Value> = groups.iter().map(|g| g["mergeable"].clone()).collect();
    assert_eq!(flags, vec![json!(false), json!(false), json!(false), json!(false), json!(true), json!(true)]);
}
