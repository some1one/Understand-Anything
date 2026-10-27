use serde_json::json;
use understand_anything::{noncode, structure};

#[test]
fn assignments_with_colons_do_not_become_make_targets() {
    let source = concat!(
        "SRC = main.c util.c\n",
        "OBJ = $(SRC:.c=.o)\n",
        "URL = https://example.com/releases\n",
        "export PATH = /usr/local/bin:$(PATH)\n",
        "EXTRA += https://example.com/extra\n",
        "DEFAULT ?= https://example.com/default\n",
        "IMMEDIATE := https://example.com/immediate\n",
        ".PHONY: build test\n",
        "\n",
        "build: $(OBJ)\n",
        "\t$(CC) -o app $(OBJ)\n",
        "test: input=name\n",
        "\techo done\n",
    );
    let analysis = noncode::analyze("makefile", source).unwrap();
    let steps = analysis["steps"].as_array().unwrap();
    assert_eq!(
        steps
            .iter()
            .map(|step| step["name"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["build", "test"]
    );
    assert_eq!(steps[0]["lineRange"], json!([10, 11]));
    assert_eq!(steps[1]["lineRange"][0], 12);
}

#[test]
fn structural_output_contains_only_real_make_targets() {
    let temp = tempfile::tempdir().unwrap();
    std::fs::write(
        temp.path().join("Makefile"),
        "OBJ = $(SRC:.c=.o)\nURL = https://example.com\nbuild: $(OBJ)\n\tcc -o app $(OBJ)\n",
    )
    .unwrap();
    let result = structure::extract_structure(&json!({
        "projectRoot":temp.path(),
        "batchFiles":[{"path":"Makefile","language":"makefile","fileCategory":"infra"}],
        "batchImportData":{}
    }))
    .unwrap();
    assert_eq!(result["filesAnalyzed"], 1);
    assert_eq!(
        result["results"][0]["steps"],
        json!([{"name":"build","startLine":3,"endLine":5}])
    );
    assert_eq!(result["results"][0]["metrics"]["stepCount"], 1);
}
