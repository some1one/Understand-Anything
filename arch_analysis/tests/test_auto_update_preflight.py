"""CLI tests for arch_analysis.auto_update_preflight against temp git repos."""

from __future__ import annotations

import json
import subprocess

import pytest

from arch_analysis import auto_update_common as c
from arch_analysis.auto_update_preflight import run
from arch_analysis.fingerprints import build_fingerprint_store


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _head(root) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A baselined git repo: a.py + b.py committed, graph/meta/fingerprints written."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("def foo(a, b):\n    return a + b\n")
    (tmp_path / "b.py").write_text("def bar():\n    return 1\n")
    (tmp_path / "README.md").write_text("# project\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    head = _head(tmp_path)

    ua = tmp_path / ".understand-anything"
    ua.mkdir()
    (ua / "knowledge-graph.json").write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "project": {"name": "t"},
                "nodes": [{"id": "file:a.py", "type": "file", "filePath": "a.py"}],
                "edges": [],
                "layers": [],
            }
        )
    )
    (ua / "meta.json").write_text(
        json.dumps({"gitCommitHash": head, "version": "1.0.0", "analyzedFiles": 2})
    )
    (ua / "fingerprints.json").write_text(
        json.dumps(build_fingerprint_store(tmp_path, ["a.py", "b.py"], head))
    )
    return tmp_path, head


def test_missing_graph_stops(tmp_path):
    res = run(tmp_path)
    assert res["status"] == "STOP"
    assert res["action"] == "NO_GRAPH"


def test_missing_meta_stops(repo):
    root, _ = repo
    (root / ".understand-anything" / "meta.json").unlink()
    res = run(root)
    assert res["status"] == "STOP"
    assert res["action"] == "NO_META"


def test_unchanged_commit_stops(repo):
    root, _ = repo
    res = run(root)
    assert res["status"] == "STOP"
    assert res["action"] == "UP_TO_DATE"


def test_force_overrides_unchanged_commit(repo):
    root, _ = repo
    # No file changes but --force: still NO_CHANGES (diff is empty), not UP_TO_DATE.
    res = run(root, force=True)
    assert res["action"] == "NO_CHANGES"
    assert res["metadataUpdated"] is True


def test_non_source_change_updates_metadata(repo):
    root, head = repo
    (root / "README.md").write_text("# project\nmore docs\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "docs")
    res = run(root)
    assert res["status"] == "STOP"
    assert res["action"] == "NO_SOURCE_CHANGES"
    assert res["metadataUpdated"] is True
    meta = json.loads((root / ".understand-anything" / "meta.json").read_text())
    assert meta["gitCommitHash"] == _head(root) != head


def test_ignored_source_change_updates_metadata(repo):
    root, _ = repo
    (root / ".understand-anything" / ".understandignore").write_text("ignored/\n")
    (root / "ignored").mkdir()
    (root / "ignored" / "x.py").write_text("def x():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "ignored source")
    res = run(root)
    assert res["status"] == "STOP"
    assert res["action"] == "ALL_IGNORED"
    assert res["metadataUpdated"] is True


def test_changed_source_continues(repo):
    root, _ = repo
    (root / "a.py").write_text("def foo(a, b, c):\n    return a + b + c\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "change a")
    res = run(root)
    assert res["status"] == "CONTINUE"
    assert res["action"] == "PROCEED"
    assert res["changedSourceFiles"] == ["a.py"]
    # Intermediate dir created for downstream phases.
    assert c.intermediate_dir(root).is_dir()
