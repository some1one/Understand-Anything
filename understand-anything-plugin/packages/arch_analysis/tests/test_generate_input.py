"""Tests for the project input generator."""

from __future__ import annotations

import subprocess

import orjson
import pytest

from arch_analysis.generate_input import generate, main
from arch_analysis.patterns import infer_node_type


def _make_tree(root):
    (root / "src").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n")
    (root / "src" / "util.py").write_text("y = 2\n")
    (root / "README.md").write_text("# readme\n")
    (root / "pyproject.toml").write_text("[project]\n")
    (root / "Dockerfile").write_text("FROM python\n")
    (root / "secret.log").write_text("noise\n")
    (root / "build").mkdir()
    (root / "build" / "out.js").write_text("//build\n")


def test_node_type_inference():
    assert infer_node_type("src/app.py") == "file"
    assert infer_node_type("README.md") == "document"
    assert infer_node_type("pyproject.toml") == "config"
    assert infer_node_type("Dockerfile") == "service"
    assert infer_node_type("infra/main.tf") == "service"
    assert infer_node_type(".github/workflows/ci.yml") == "pipeline"
    assert infer_node_type("db/schema.sql") == "schema"


def test_generate_in_git_repo_respects_gitignore(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    payload = generate(tmp_path)
    paths = {n["filePath"] for n in payload["fileNodes"]}

    assert "src/app.py" in paths
    assert "README.md" in paths
    assert "secret.log" not in paths       # .gitignore *.log
    assert "build/out.js" not in paths     # .gitignore build/
    assert payload["importEdges"] == []
    assert payload["allEdges"] == []


def test_generate_non_git_uses_pathspec_fallback(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    # No git init -> pathspec fallback parses root .gitignore.
    paths = {n["filePath"] for n in generate(tmp_path)["fileNodes"]}
    assert "secret.log" not in paths
    assert "build/out.js" not in paths
    assert "src/util.py" in paths


def test_no_gitignore_includes_everything(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n")
    paths = {n["filePath"] for n in generate(tmp_path, respect_gitignore=False)["fileNodes"]}
    assert "secret.log" in paths


def test_include_whitelist(tmp_path):
    _make_tree(tmp_path)
    paths = {n["filePath"] for n in generate(tmp_path, include=["*.py"])["fileNodes"]}
    assert paths == {"src/app.py", "src/util.py"}


def test_exclude_globs(tmp_path):
    _make_tree(tmp_path)
    paths = {n["filePath"] for n in generate(tmp_path, exclude=["docs/**", "*.md"])["fileNodes"]}
    assert "README.md" not in paths
    assert "src/app.py" in paths


def test_node_ids_carry_inferred_type(tmp_path):
    _make_tree(tmp_path)
    nodes = {n["filePath"]: n for n in generate(tmp_path, respect_gitignore=False)["fileNodes"]}
    assert nodes["Dockerfile"]["id"] == "service:Dockerfile"
    assert nodes["Dockerfile"]["type"] == "service"
    assert nodes["README.md"]["type"] == "document"


def test_cli_writes_file(tmp_path):
    _make_tree(tmp_path)
    out = tmp_path / "input.json"
    rc = main([str(tmp_path), str(out), "--include", "*.py"])
    assert rc == 0
    payload = orjson.loads(out.read_bytes())
    assert {n["filePath"] for n in payload["fileNodes"]} == {"src/app.py", "src/util.py"}


def test_cli_rejects_missing_dir(tmp_path):
    assert main([str(tmp_path / "nope"), str(tmp_path / "out.json")]) == 1
