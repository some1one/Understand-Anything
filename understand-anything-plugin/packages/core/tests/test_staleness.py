"""Port of packages/core/src/__tests__/staleness.test.ts."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from understand_core import staleness
from understand_core.staleness import get_changed_files, is_stale, merge_graph_update


def make_node(**overrides):
    base = {"type": "file", "summary": "", "tags": [], "complexity": "simple"}
    base.update(overrides)
    return base


def make_edge(**overrides):
    base = {"type": "imports", "direction": "forward", "weight": 1}
    base.update(overrides)
    return base


def make_graph(**overrides):
    base = {
        "version": "1.0.0",
        "project": {
            "name": "test-project",
            "languages": ["typescript"],
            "frameworks": [],
            "description": "A test project",
            "analyzedAt": "2026-01-01T00:00:00.000Z",
            "gitCommitHash": "abc123",
        },
        "nodes": [],
        "edges": [],
        "layers": [],
    }
    base.update(overrides)
    return base


# --- getChangedFiles ---


def test_returns_changed_files(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="src/index.ts\nsrc/utils.ts\n")

    monkeypatch.setattr(staleness.subprocess, "run", fake_run)
    result = get_changed_files("/project", "abc123")
    assert result == ["src/index.ts", "src/utils.ts"]
    assert captured["cmd"] == ["git", "diff", "abc123..HEAD", "--name-only"]
    assert captured["kwargs"]["cwd"] == "/project"


def test_returns_empty_when_no_changes(monkeypatch):
    monkeypatch.setattr(staleness.subprocess, "run", lambda cmd, **kw: SimpleNamespace(stdout=""))
    assert get_changed_files("/project", "abc123") == []


def test_returns_empty_on_git_error(monkeypatch):
    def fail(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="fatal: bad revision")

    monkeypatch.setattr(staleness.subprocess, "run", fail)
    assert get_changed_files("/project", "abc123") == []


# --- isStale ---


def test_is_stale_when_changes(monkeypatch):
    monkeypatch.setattr(staleness.subprocess, "run", lambda cmd, **kw: SimpleNamespace(stdout="src/index.ts\n"))
    assert is_stale("/project", "abc123") == {"stale": True, "changedFiles": ["src/index.ts"]}


def test_not_stale_when_no_changes(monkeypatch):
    monkeypatch.setattr(staleness.subprocess, "run", lambda cmd, **kw: SimpleNamespace(stdout=""))
    assert is_stale("/project", "abc123") == {"stale": False, "changedFiles": []}


# --- mergeGraphUpdate ---


def test_replaces_nodes_for_changed_files():
    existing = make_graph(nodes=[
        make_node(id="file-a", name="a.ts", filePath="src/a.ts", summary="Old summary"),
        make_node(id="file-b", name="b.ts", filePath="src/b.ts", summary="Unchanged"),
        make_node(id="func-a1", name="funcA1", type="function", filePath="src/a.ts", summary="Old function"),
    ])
    new_nodes = [
        make_node(id="file-a-v2", name="a.ts", filePath="src/a.ts", summary="New summary"),
        make_node(id="func-a2", name="funcA2", type="function", filePath="src/a.ts", summary="New function"),
    ]
    result = merge_graph_update(existing, ["src/a.ts"], new_nodes, [], "def456")
    ids = {n["id"] for n in result["nodes"]}
    assert "file-a" not in ids
    assert "func-a1" not in ids
    assert "file-a-v2" in ids
    assert "func-a2" in ids
    assert "file-b" in ids


def test_removes_edges_from_changed_files():
    existing = make_graph(
        nodes=[
            make_node(id="file-a", name="a.ts", filePath="src/a.ts"),
            make_node(id="file-b", name="b.ts", filePath="src/b.ts"),
            make_node(id="file-c", name="c.ts", filePath="src/c.ts"),
        ],
        edges=[
            make_edge(source="file-a", target="file-b"),
            make_edge(source="file-b", target="file-c"),
            make_edge(source="file-c", target="file-a"),
        ],
    )
    new_nodes = [make_node(id="file-a-v2", name="a.ts", filePath="src/a.ts", summary="Updated")]
    new_edges = [make_edge(source="file-a-v2", target="file-c")]
    result = merge_graph_update(existing, ["src/a.ts"], new_nodes, new_edges, "def456")

    def find(src, tgt):
        return next((e for e in result["edges"] if e["source"] == src and e["target"] == tgt), None)

    assert find("file-a", "file-b") is None
    assert find("file-b", "file-c") is not None
    assert find("file-c", "file-a") is None
    assert find("file-a-v2", "file-c") is not None


def test_updates_timestamp_and_commit_hash():
    from datetime import datetime, timezone

    existing = make_graph()
    before = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    result = merge_graph_update(existing, [], [], [], "def456")
    after = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    assert result["project"]["gitCommitHash"] == "def456"
    assert result["project"]["analyzedAt"] >= before
    assert result["project"]["analyzedAt"] <= after
