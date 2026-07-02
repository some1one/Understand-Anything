"""Integration tests for the auto-update apply/finalize phases on small fixtures."""

from __future__ import annotations

import json
import subprocess

import pytest

from arch_analysis import auto_update_apply_batches as apply_batches
from arch_analysis import auto_update_common as c
from arch_analysis import auto_update_fingerprint_check as fp_check
from arch_analysis import auto_update_finalize as finalize
from arch_analysis import auto_update_preflight as preflight
from arch_analysis.fingerprints import build_fingerprint_store


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _head(root) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()


def _file_node(path):
    return {
        "id": f"file:{path}",
        "type": "file",
        "name": path.rsplit("/", 1)[-1],
        "summary": f"file {path}",
        "tags": [],
        "complexity": "simple",
        "filePath": path,
    }


@pytest.fixture
def repo(tmp_path):
    """Baseline repo with src/f0..f5, a graph + one layer + one import edge."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    paths = [f"src/f{i}.py" for i in range(6)]
    for p in paths:
        (tmp_path / p).write_text(f"def fn{p[-4]}():\n    return 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    head = _head(tmp_path)

    ua = tmp_path / ".understand-anything"
    ua.mkdir()
    inter = ua / "intermediate"
    inter.mkdir()
    graph = {
        "version": "1.0.0",
        "project": {"name": "t", "languages": ["Python"], "frameworks": [], "description": "x"},
        "nodes": [_file_node(p) for p in paths],
        "edges": [
            {
                "source": "file:src/f0.py",
                "target": "file:src/f1.py",
                "type": "imports",
                "direction": "forward",
                "weight": 0.7,
            }
        ],
        "layers": [
            {
                "id": "layer:core",
                "name": "Core",
                "description": "core",
                "nodeIds": [f"file:{p}" for p in paths],
            }
        ],
    }
    (ua / "knowledge-graph.json").write_text(json.dumps(graph))
    (ua / "meta.json").write_text(
        json.dumps({"gitCommitHash": head, "version": "1.0.0", "analyzedFiles": 6})
    )
    (ua / "fingerprints.json").write_text(
        json.dumps(build_fingerprint_store(tmp_path, paths, head))
    )
    (inter / "scan-result.json").write_text(
        json.dumps(
            {
                "files": [
                    {"path": p, "language": "Python", "sizeLines": 2, "fileCategory": "code"}
                    for p in paths
                ],
                "importMap": {"src/f0.py": ["src/f1.py"]},
            }
        )
    )
    return tmp_path, head, paths


def _drive_to_change_analysis(root):
    """Run preflight + fingerprint check, persisting their state files."""
    state = preflight.run(root)
    c.write_json(c.state_path(root), state)
    analysis = fp_check.run(root)
    c.write_json(c.change_analysis_path(root), analysis)
    return analysis


def test_partial_update_prunes_merges_and_places_new_file(repo):
    root, head, _paths = repo

    # Modify f0 structurally, add f6 (same dir), delete f1.
    (root / "src/f0.py").write_text("def fn0():\n    return 1\n\ndef extra():\n    return 2\n")
    (root / "src/f6.py").write_text("def fn6():\n    return 6\n")
    (root / "src/f1.py").unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "change")
    new_head = _head(root)

    analysis = _drive_to_change_analysis(root)
    assert analysis["action"] == "PARTIAL_UPDATE"
    assert analysis["rerunArchitecture"] is False
    assert set(analysis["filesToReanalyze"]) == {"src/f0.py", "src/f6.py"}
    assert analysis["deletedFiles"] == ["src/f1.py"]
    assert analysis["newFiles"] == ["src/f6.py"]

    # Simulate the file-analyzer producing fresh nodes for the reanalyzed files.
    inter = c.intermediate_dir(root)
    (inter / "batch-1.json").write_text(
        json.dumps(
            {
                "nodes": [_file_node("src/f0.py"), _file_node("src/f6.py")],
                "edges": [],
            }
        )
    )

    apply_batches.run(root)
    merged = json.loads(c.merged_graph_path(root).read_text())
    ids = {n["id"] for n in merged["nodes"]}
    # Deleted file pruned; unchanged files kept; reanalyzed files present.
    assert "file:src/f1.py" not in ids
    assert {"file:src/f0.py", "file:src/f2.py", "file:src/f6.py"} <= ids
    # Dangling edge into the deleted node was dropped.
    assert all(
        e["target"] != "file:src/f1.py" and e["source"] != "file:src/f1.py"
        for e in merged["edges"]
    )

    summary = finalize.run(root)
    assert summary["status"] == "UPDATED"

    final = json.loads(c.graph_path(root).read_text())
    layer = next(layer for layer in final["layers"] if layer["id"] == "layer:core")
    # New file deterministically placed into the existing layer by directory.
    assert "file:src/f6.py" in layer["nodeIds"]
    # Deleted file removed from every layer.
    assert all(
        "file:src/f1.py" not in layer["nodeIds"] for layer in final["layers"]
    )
    # Every file node sits in exactly one layer.
    seen = [nid for layer in final["layers"] for nid in layer["nodeIds"]]
    assert len(seen) == len(set(seen))

    # Fingerprints patched: unchanged entries preserved, deleted removed, new added.
    fps = json.loads((root / ".understand-anything" / "fingerprints.json").read_text())
    assert "src/f2.py" in fps["files"]  # untouched, preserved
    assert "src/f6.py" in fps["files"]  # new, added
    assert "src/f1.py" not in fps["files"]  # deleted, removed
    assert any(f["name"] == "extra" for f in fps["files"]["src/f0.py"]["functions"])

    # Metadata advanced to the new commit, only after a successful patch.
    meta = json.loads((root / ".understand-anything" / "meta.json").read_text())
    assert meta["gitCommitHash"] == new_head
    assert summary["metadataUpdated"] is True

    # Intermediate cleaned, but scan-result.json preserved.
    left = {p.name for p in c.intermediate_dir(root).iterdir()}
    assert "scan-result.json" in left
    assert "batch-1.json" not in left
    assert "change-analysis.json" not in left


def test_cosmetic_change_skips_with_metadata_bump(repo):
    root, head, _ = repo
    # Body-only edit to f0 — no structural change.
    (root / "src/f0.py").write_text("def fn0():\n    return 1 + 0\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "cosmetic")
    new_head = _head(root)

    analysis = _drive_to_change_analysis(root)
    assert analysis["action"] == "SKIP"
    assert analysis["metadataUpdated"] is True
    meta = json.loads((root / ".understand-anything" / "meta.json").read_text())
    assert meta["gitCommitHash"] == new_head
