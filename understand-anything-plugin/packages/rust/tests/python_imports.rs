use serde_json::json;
use understand_anything::imports::{ResolutionContext, resolve_python_import};

#[test]
fn relative_names_fall_back_to_packages_without_displacing_submodules() {
    let temp = tempfile::tempdir().unwrap();
    let files = [
        "__init__.py",
        "pkg/__init__.py",
        "pkg/stats/__init__.py",
        "pkg/stats/regression.py",
        "pkg/stats/child/__init__.py",
        "namespace/module.py",
        "lone/__init__.py",
    ]
    .map(|path| json!({"path":path, "language":"python"}));
    let context = ResolutionContext::new(temp.path(), &files);
    for (source, path, names, expected) in [
        (
            "..",
            "pkg/stats/regression.py",
            vec!["BaseAnalyzer"],
            vec!["pkg/__init__.py"],
        ),
        (
            ".",
            "pkg/stats/other.py",
            vec!["regression", "LIMIT", "MORE", "child"],
            vec![
                "pkg/stats/regression.py",
                "pkg/stats/__init__.py",
                "pkg/stats/child/__init__.py",
            ],
        ),
        ("..", "pkg/core/star.py", vec!["*"], vec!["pkg/__init__.py"]),
        (
            ".",
            "pkg/stats/other.py",
            vec!["regression"],
            vec!["pkg/stats/regression.py"],
        ),
        (".", "lone/__init__.py", vec!["NAME", "*"], vec![]),
        (
            ".",
            "namespace/main.py",
            vec!["module", "MISSING", "*"],
            vec!["namespace/module.py"],
        ),
        (".", "main.py", vec!["NAME", "*"], vec!["__init__.py"]),
        (".", "pkg/main.py", vec!["", "Foo.bar"], vec![]),
        (".", "pkg/main.py", vec![], vec![]),
        ("....", "pkg/main.py", vec!["NAME"], vec![]),
    ] {
        let names = names.into_iter().map(str::to_owned).collect::<Vec<_>>();
        assert_eq!(
            resolve_python_import(source, &names, path, &context),
            expected,
            "{source} {names:?} in {path}"
        );
    }
}

#[test]
#[ignore = "requires Python grammar; run with UA_TEST_PARSER_CACHE"]
fn parsed_relative_imports_preserve_package_edges() {
    if let Ok(cache) = std::env::var("UA_TEST_PARSER_CACHE") {
        understand_anything::parsers::configure(Some(std::path::Path::new(&cache))).unwrap();
    }
    let temp = tempfile::tempdir().unwrap();
    let sources = [
        ("pkg/__init__.py", "class BaseAnalyzer:\n    pass\n"),
        ("pkg/stats/__init__.py", "LIMIT = 10\n"),
        ("pkg/stats/regression.py", "from .. import BaseAnalyzer\nfrom . import LIMIT\n"),
        ("pkg/stats/other.py", "from . import regression, LIMIT, MORE\n"),
        ("pkg/star.py", "from . import *\n"),
        ("lone/__init__.py", "from . import NAME\n"),
    ];
    let files = sources.iter().map(|(path, source)| {
        let dest = temp.path().join(path);
        std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
        std::fs::write(dest, source).unwrap();
        json!({"path":path,"language":"python","fileCategory":"code"})
    }).collect::<Vec<_>>();
    let result = understand_anything::imports::extract_import_map(&json!({
        "projectRoot":temp.path(),"files":files
    })).unwrap();
    assert_eq!(result["importMap"]["pkg/stats/regression.py"], json!(["pkg/__init__.py", "pkg/stats/__init__.py"]));
    assert_eq!(result["importMap"]["pkg/stats/other.py"], json!(["pkg/stats/__init__.py", "pkg/stats/regression.py"]));
    assert_eq!(result["importMap"]["pkg/star.py"], json!(["pkg/__init__.py"]));
    assert_eq!(result["importMap"]["lone/__init__.py"], json!([]));
}
