//! File-node identity and baseline tags shared by seeding and finalization.
pub fn basename(path: &str) -> &str {
    path.rsplit('/').next().unwrap_or(path)
}
fn ext(path: &str) -> String {
    basename(path)
        .rsplit_once('.')
        .map(|(_, e)| e.to_lowercase())
        .unwrap_or_default()
}
fn infra_type(path: &str) -> &'static str {
    let base = basename(path);
    if path.starts_with(".github/workflows/")
        || path == ".gitlab-ci.yml"
        || base == "Jenkinsfile"
        || path.starts_with(".circleci/")
    {
        "pipeline"
    } else if ["tf", "tfvars"].contains(&ext(path).as_str()) || base == "Vagrantfile" {
        "resource"
    } else {
        "service"
    }
}
pub fn file_level_node(category: Option<&str>, path: &str) -> Option<(String, String)> {
    let typ = match category {
        Some("config") => "config",
        Some("docs") => "document",
        Some("infra") => infra_type(path),
        Some("data") => {
            if ["graphql", "gql", "proto", "prisma"].contains(&ext(path).as_str()) {
                "schema"
            } else {
                return None;
            }
        }
        _ => "file",
    };
    Some((typ.into(), format!("{typ}:{path}")))
}
pub fn is_test_file(path: &str) -> bool {
    let b = basename(path);
    let (stem, ext) = b
        .rsplit_once('.')
        .filter(|(s, _)| !s.is_empty())
        .unwrap_or((b, ""));
    let ext = ext.to_lowercase();
    match ext.as_str() {
        "ts" | "tsx" | "js" | "jsx" | "mjs" | "cjs" | "vue" => {
            stem.ends_with(".test") || stem.ends_with(".spec")
        }
        "py" | "c" | "cpp" | "cc" => stem.starts_with("test_") || stem.ends_with("_test"),
        "go" => stem.ends_with("_test"),
        "java" => ["Test", "Tests", "IT"].iter().any(|s| stem.ends_with(s)),
        "kt" | "cs" => ["Test", "Tests"].iter().any(|s| stem.ends_with(s)),
        _ => false,
    }
}
pub fn deterministic_tags(category: Option<&str>, path: &str) -> Vec<String> {
    let mut tags = vec![];
    let b = basename(path);
    let e = ext(path);
    if is_test_file(path) {
        tags.push("test");
    }
    if [
        "index.ts",
        "index.js",
        "index.tsx",
        "index.jsx",
        "__init__.py",
        "manage.py",
        "main.py",
        "__main__.py",
        "main.go",
        "main.rs",
        "lib.rs",
        "Application.java",
        "Main.java",
        "Program.cs",
        "config.ru",
    ]
    .contains(&b)
    {
        tags.push("entry-point");
    }
    if b == "mod.rs" {
        tags.push("barrel");
    }
    match category {
        Some("infra") => {
            if b == "Dockerfile" || b.starts_with("Dockerfile.") {
                tags.extend(["containerization", "infrastructure"]);
            } else if b.starts_with("docker-compose.") || b.starts_with("compose.") {
                tags.extend(["orchestration", "infrastructure"]);
            } else if infra_type(path) == "pipeline" {
                tags.extend(["ci-cd", "deployment"]);
            } else if infra_type(path) == "resource" {
                tags.extend(["infrastructure", "deployment"]);
            } else {
                tags.push("infrastructure");
            }
        }
        Some("config") => tags.push("configuration"),
        Some("docs") => tags.push("documentation"),
        Some("data") => match e.as_str() {
            "sql" => tags.extend(["database", "migration"]),
            "graphql" | "gql" => tags.extend(["api-schema", "schema-definition"]),
            "proto" | "prisma" => tags.extend(["schema-definition", "data-pipeline"]),
            _ => {}
        },
        _ => {}
    }
    let mut result = vec![];
    for tag in tags {
        if !result.iter().any(|s| s == tag) {
            result.push(tag.to_owned());
        }
    }
    result
}
