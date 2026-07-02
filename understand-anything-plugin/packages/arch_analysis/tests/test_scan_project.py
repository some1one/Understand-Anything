"""Parity tests for arch_analysis.scan_project (ported from the .mjs suite)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arch_analysis.languages import (
    detect_category,
    detect_language,
    estimate_complexity,
)
from arch_analysis.scan_project import scan_project


def _git_init(root: Path) -> None:
    try:
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)
    except (FileNotFoundError, OSError):
        pass


def setup_tree(tmp_path: Path, files: dict[str, str], git_init: bool = True) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    for rel, contents in files.items():
        abs_path = root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(contents, encoding="utf-8")
    if git_init:
        _git_init(root)
    return root


def by_path(output: dict, path: str) -> dict | None:
    for f in output["files"]:
        if f["path"] == path:
            return f
    return None


# --- language detection -----------------------------------------------------


def test_typescript_javascript_extensions(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "a.ts": "export const a = 1;\n",
            "b.tsx": "export const B = () => null;\n",
            "c.js": "module.exports = {};\n",
            "d.jsx": "export default () => null;\n",
            "e.mjs": "export const e = 1;\n",
            "f.cjs": "module.exports = 1;\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "a.ts")["language"] == "typescript"
    assert by_path(out, "b.tsx")["language"] == "typescript"
    assert by_path(out, "c.js")["language"] == "javascript"
    assert by_path(out, "d.jsx")["language"] == "javascript"
    assert by_path(out, "e.mjs")["language"] == "javascript"
    assert by_path(out, "f.cjs")["language"] == "javascript"


def test_systems_languages(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "a.py": "x = 1\n",
            "b.go": "package main\n",
            "c.rs": "fn main() {}\n",
            "d.java": "class D {}\n",
            "e.kt": "fun main() {}\n",
            "f.cs": "class F {}\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "a.py")["language"] == "python"
    assert by_path(out, "b.go")["language"] == "go"
    assert by_path(out, "c.rs")["language"] == "rust"
    assert by_path(out, "d.java")["language"] == "java"
    assert by_path(out, "e.kt")["language"] == "kotlin"
    assert by_path(out, "f.cs")["language"] == "csharp"


def test_ruby_php_c_cpp(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "a.rb": "puts 1\n",
            "b.php": "<?php echo 1;\n",
            "c.c": "int main() { return 0; }\n",
            "d.h": "void f();\n",
            "e.cpp": "int main() {}\n",
            "f.hpp": "class F {};\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "a.rb")["language"] == "ruby"
    assert by_path(out, "b.php")["language"] == "php"
    assert by_path(out, "c.c")["language"] == "c"
    assert by_path(out, "d.h")["language"] == "c"
    assert by_path(out, "e.cpp")["language"] == "cpp"
    assert by_path(out, "f.hpp")["language"] == "cpp"


def test_config_formats(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "a.yaml": "x: 1\n",
            "b.yml": "x: 1\n",
            "c.json": "{}\n",
            "d.jsonc": "{ /* c */ }\n",
            "e.toml": "x = 1\n",
            "f.xml": "<x/>\n",
            "g.md": "# h\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "a.yaml")["language"] == "yaml"
    assert by_path(out, "c.json")["language"] == "json"
    assert by_path(out, "d.jsonc")["language"] == "jsonc"
    assert by_path(out, "e.toml")["language"] == "toml"
    assert by_path(out, "f.xml")["language"] == "xml"
    assert by_path(out, "g.md")["language"] == "markdown"


def test_shell_dockerfile_and_unsupported_excluded(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "a.sh": "echo 1\n",
            "b.bat": "@echo off\n",
            "c.cmd": "@echo off\n",
            "deploy.ps1": "Write-Output 1\n",
            "Dockerfile": "FROM node:22\n",
            "Dockerfile.dev": "FROM node:22\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "a.sh")["language"] == "shell"
    assert by_path(out, "b.bat") is None
    assert by_path(out, "c.cmd") is None
    assert by_path(out, "deploy.ps1") is None
    assert by_path(out, "Dockerfile")["language"] == "dockerfile"
    assert by_path(out, "Dockerfile.dev")["language"] == "dockerfile"


def test_unknown_and_bare_extension_fallback(tmp_path):
    root = setup_tree(
        tmp_path,
        {"WEIRD_FILE": "mystery\n", "data.weirdext": "some data\n"},
    )
    out = scan_project(root)
    assert by_path(out, "WEIRD_FILE")["language"] == "unknown"
    assert by_path(out, "data.weirdext")["language"] == "weirdext"


# --- category assignment ----------------------------------------------------


def test_category_code(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "src/a.ts": "export const a = 1;\n",
            "src/b.py": "def b(): pass\n",
            "src/c.go": "package main\n",
            "src/d.rs": "fn main() {}\n",
        },
    )
    out = scan_project(root)
    for p in ("src/a.ts", "src/b.py", "src/c.go", "src/d.rs"):
        assert by_path(out, p)["fileCategory"] == "code"


def test_category_config(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "package.json": "{}\n",
            "pyproject.toml": "[project]\nname='p'\n",
            "config.yaml": "x: 1\n",
            "app.ini": "[s]\nk=v\n",
            "data.xml": "<x/>\n",
        },
    )
    out = scan_project(root)
    for p in ("package.json", "pyproject.toml", "config.yaml", "app.ini", "data.xml"):
        assert by_path(out, p)["fileCategory"] == "config"


def test_category_docs_but_not_license(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "README.md": "# x\n",
            "docs/guide.rst": "Guide\n=====\n",
            "NOTES.txt": "notes\n",
            "LICENSE": "Apache-2.0\n",
            ".understandignore": "!LICENSE\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "README.md")["fileCategory"] == "docs"
    assert by_path(out, "docs/guide.rst")["fileCategory"] == "docs"
    assert by_path(out, "NOTES.txt")["fileCategory"] == "docs"
    license_entry = by_path(out, "LICENSE")
    assert license_entry is not None
    assert license_entry["fileCategory"] != "docs"


def test_category_infra(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "Dockerfile": "FROM node:22\n",
            "docker-compose.yml": "services: {}\n",
            ".gitlab-ci.yml": "stages: []\n",
            "infra/main.tf": 'resource "x" "y" {}\n',
            ".github/workflows/ci.yml": "name: ci\n",
            "Makefile": "all:\n\t@echo hi\n",
            "Jenkinsfile": "pipeline { }\n",
            "k8s/deploy.yaml": "kind: Deployment\n",
            "kubernetes/svc.yaml": "kind: Service\n",
            "foo.k8s.yaml": "kind: ConfigMap\n",
        },
    )
    out = scan_project(root)
    for p in (
        "Dockerfile",
        "docker-compose.yml",
        ".gitlab-ci.yml",
        "infra/main.tf",
        ".github/workflows/ci.yml",
        "Makefile",
        "Jenkinsfile",
        "k8s/deploy.yaml",
        "kubernetes/svc.yaml",
        "foo.k8s.yaml",
    ):
        assert by_path(out, p)["fileCategory"] == "infra", p


def test_category_data(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "db/schema.sql": "CREATE TABLE x (id INT);\n",
            "api/schema.graphql": "type X { id: ID! }\n",
            "api/types.proto": 'syntax = "proto3";\n',
            "prisma/schema.prisma": "model X { id Int @id }\n",
            "data/seed.csv": "a,b\n1,2\n",
        },
    )
    out = scan_project(root)
    for p in (
        "db/schema.sql",
        "api/schema.graphql",
        "api/types.proto",
        "prisma/schema.prisma",
        "data/seed.csv",
    ):
        assert by_path(out, p)["fileCategory"] == "data", p


def test_category_script_and_markup(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            "scripts/build.sh": "#!/bin/bash\n",
            "scripts/run.bash": "#!/bin/bash\n",
            "public/index.html": "<!doctype html>\n",
            "styles/app.css": "body { }\n",
            "styles/app.scss": "$x: 1;\n",
            "styles/app.less": "@x: 1;\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "scripts/build.sh")["fileCategory"] == "script"
    assert by_path(out, "scripts/run.bash")["fileCategory"] == "script"
    assert by_path(out, "public/index.html")["fileCategory"] == "markup"
    assert by_path(out, "styles/app.css")["fileCategory"] == "markup"
    assert by_path(out, "styles/app.less")["fileCategory"] == "markup"


def test_docker_compose_priority_over_config(tmp_path):
    root = setup_tree(tmp_path, {"docker-compose.yml": "services: {}\n"})
    out = scan_project(root)
    assert by_path(out, "docker-compose.yml")["fileCategory"] == "infra"
    assert by_path(out, "docker-compose.yml")["language"] == "yaml"


def test_dotfile_configs(tmp_path):
    root = setup_tree(
        tmp_path,
        {".env": "API_KEY=abc\n", ".env.local": "LOCAL=1\n", ".env.production": "PROD=1\n"},
    )
    out = scan_project(root)
    for p in (".env", ".env.local", ".env.production"):
        assert by_path(out, p)["fileCategory"] == "config", p
        assert by_path(out, p)["language"] == "config", p


# --- ignore handling --------------------------------------------------------


def test_understandignore_increments_filtered(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            ".understandignore": "fixtures/\n",
            "src/index.ts": "export const x = 1;\n",
            "fixtures/snap1.json": '{ "a": 1 }\n',
            "fixtures/snap2.json": '{ "b": 2 }\n',
        },
    )
    out = scan_project(root)
    assert by_path(out, "fixtures/snap1.json") is None
    assert by_path(out, "fixtures/snap2.json") is None
    assert out["filteredByIgnore"] == 2


def test_negation_reincludes_default_excluded(tmp_path):
    root = setup_tree(
        tmp_path,
        {
            ".understandignore": "!keep.log\n",
            "src/index.ts": "export const x = 1;\n",
            "keep.log": "important\n",
            "drop.log": "noise\n",
        },
    )
    out = scan_project(root)
    assert by_path(out, "keep.log") is not None
    assert by_path(out, "drop.log") is None
    assert out["filteredByIgnore"] == 0


# --- determinism / empty / thresholds --------------------------------------


def test_determinism(tmp_path):
    files = {
        "README.md": "# project\n",
        "src/a.ts": "export const a = 1;\n",
        "src/b.ts": "export const b = 2;\n",
        "src/lib/c.ts": "export const c = 3;\n",
        "package.json": "{}\n",
        "tsconfig.json": "{}\n",
    }
    root = setup_tree(tmp_path, files)
    import json

    assert json.dumps(scan_project(root)) == json.dumps(scan_project(root))


def test_empty_repo(tmp_path):
    root = setup_tree(tmp_path, {}, git_init=True)
    out = scan_project(root)
    assert out["scriptCompleted"] is True
    assert out["totalFiles"] == 0
    assert out["files"] == []
    assert out["filteredByIgnore"] == 0
    assert out["estimatedComplexity"] == "small"


@pytest.mark.parametrize(
    "n,expected",
    [(30, "small"), (31, "moderate"), (150, "moderate"), (151, "large"), (501, "very-large")],
)
def test_complexity_thresholds(tmp_path, n, expected):
    files = {f"f{i:04d}.ts": "export const x = 1;\n" for i in range(n)}
    root = setup_tree(tmp_path, files)
    out = scan_project(root)
    assert out["totalFiles"] == n
    assert out["estimatedComplexity"] == expected


def test_files_sorted(tmp_path):
    root = setup_tree(
        tmp_path,
        {"zzz.ts": "\n", "aaa.ts": "\n", "mmm.ts": "\n", "subdir/file.ts": "\n"},
    )
    out = scan_project(root)
    paths = [f["path"] for f in out["files"]]
    assert paths == sorted(paths)


def test_output_schema_invariants(tmp_path):
    root = setup_tree(
        tmp_path,
        {"src/a.ts": "export const a = 1;\n", "README.md": "# x\n", "package.json": "{}\n"},
    )
    out = scan_project(root)
    assert out["scriptCompleted"] is True
    assert out["totalFiles"] == len(out["files"])
    assert out["stats"]["filesScanned"] == len(out["files"])
    assert out["estimatedComplexity"] in {"small", "moderate", "large", "very-large"}
    for f in out["files"]:
        assert f["fileCategory"] in {
            "code",
            "config",
            "docs",
            "infra",
            "data",
            "script",
            "markup",
        }


# --- unit helpers -----------------------------------------------------------


def test_helpers_direct():
    assert detect_language("a.ts") == "typescript"
    assert detect_language("Dockerfile.prod") == "dockerfile"
    assert detect_category("x.md") == "docs"
    assert detect_category("LICENSE") == "code"
    assert estimate_complexity(0) == "small"
    assert estimate_complexity(1000) == "very-large"
