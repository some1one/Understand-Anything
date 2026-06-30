"""importMap recovery tests for arch_analysis.merge_batch_graphs.

Ported from understand-anything-plugin/src/__tests__/merge-recover-imports.test.mjs.
Shells out to `python -m arch_analysis.merge_batch_graphs` so the full CLI path
(batch discovery → merge → importMap recovery) is exercised.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_node(path: str) -> dict:
    return {
        "id": f"file:{path}",
        "type": "file",
        "name": path.rsplit("/", 1)[-1],
        "filePath": path,
        "summary": "",
        "tags": [],
        "complexity": "simple",
    }


def _imports_edge(src: str, tgt: str) -> dict:
    return {
        "source": f"file:{src}",
        "target": f"file:{tgt}",
        "type": "imports",
        "direction": "forward",
        "weight": 0.7,
    }


@pytest.fixture
def project(tmp_path):
    intermediate = tmp_path / ".understand-anything" / "intermediate"
    intermediate.mkdir(parents=True)
    return tmp_path, intermediate


def _run_merge(project_root: Path, intermediate: Path):
    result = subprocess.run(
        [sys.executable, "-m", "arch_analysis.merge_batch_graphs", str(project_root)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"merge failed: {result.returncode}\n{result.stderr}")
    assembled = json.loads((intermediate / "assembled-graph.json").read_text())
    return assembled, result.stderr


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data))


def test_recovers_dropped_imports(project):
    root, inter = project
    _write(
        inter / "batch-0.json",
        {
            "nodes": [_file_node(f"src/{n}.py") for n in "abcd"],
            "edges": [_imports_edge("src/a.py", "src/b.py")],
        },
    )
    _write(
        inter / "scan-result.json",
        {"importMap": {"src/a.py": ["src/b.py", "src/c.py", "src/d.py"], "src/b.py": []}},
    )
    assembled, stderr = _run_merge(root, inter)
    imports = [e for e in assembled["edges"] if e["type"] == "imports"]
    assert len(imports) == 3
    assert {e["target"] for e in imports} == {"file:src/b.py", "file:src/c.py", "file:src/d.py"}
    recovered = [e for e in imports if e.get("recoveredFromImportMap")]
    assert len(recovered) == 2
    assert "Recovered 2 `imports` edges" in stderr


def test_no_duplicate_edges(project):
    root, inter = project
    _write(
        inter / "batch-0.json",
        {
            "nodes": [_file_node("src/a.py"), _file_node("src/b.py")],
            "edges": [_imports_edge("src/a.py", "src/b.py")],
        },
    )
    _write(inter / "scan-result.json", {"importMap": {"src/a.py": ["src/b.py"], "src/b.py": []}})
    assembled, stderr = _run_merge(root, inter)
    assert len([e for e in assembled["edges"] if e["type"] == "imports"]) == 1
    assert "Recovered 0 `imports` edges" in stderr


def test_skips_missing_source(project):
    root, inter = project
    _write(inter / "batch-0.json", {"nodes": [_file_node("src/b.py")], "edges": []})
    _write(inter / "scan-result.json", {"importMap": {"src/missing.py": ["src/b.py"]}})
    assembled, stderr = _run_merge(root, inter)
    assert len([e for e in assembled["edges"] if e["type"] == "imports"]) == 0
    assert "Skipped 1 importMap source files with no `file:` node" in stderr


def test_skips_missing_targets(project):
    root, inter = project
    _write(inter / "batch-0.json", {"nodes": [_file_node("src/a.py")], "edges": []})
    _write(
        inter / "scan-result.json",
        {"importMap": {"src/a.py": ["src/dropped.py", "src/also-missing.py"]}},
    )
    assembled, stderr = _run_merge(root, inter)
    assert len([e for e in assembled["edges"] if e["type"] == "imports"]) == 0
    assert "Skipped 2 importMap target paths with no `file:` node" in stderr


def test_works_without_scan_result(project):
    root, inter = project
    _write(
        inter / "batch-0.json",
        {
            "nodes": [_file_node("src/a.py"), _file_node("src/b.py")],
            "edges": [_imports_edge("src/a.py", "src/b.py")],
        },
    )
    assembled, stderr = _run_merge(root, inter)
    assert len([e for e in assembled["edges"] if e["type"] == "imports"]) == 1
    assert "importMap recovery skipped — scan-result.json not found" in stderr


def test_never_self_imports(project):
    root, inter = project
    _write(inter / "batch-0.json", {"nodes": [_file_node("src/a.py")], "edges": []})
    _write(inter / "scan-result.json", {"importMap": {"src/a.py": ["src/a.py"]}})
    assembled, _ = _run_merge(root, inter)
    assert len([e for e in assembled["edges"] if e["type"] == "imports"]) == 0
