"""Tests for understand_core.assemble_part_graph."""

from __future__ import annotations

from understand_core.assemble_part_graph import build_part_graph


def _node(nid):
    return {"id": nid, "type": "file", "name": nid, "summary": "s", "tags": [], "complexity": "simple"}


SCAN = {
    "name": "proj",
    "description": "d",
    "languages": ["python"],
    "frameworks": [],
    "files": [{"path": "src/api/h.py"}, {"path": "src/db/conn.py"}],
}


def test_tags_part_and_metadata():
    assembled = {"nodes": [_node("file:src/api/h.py")], "edges": []}
    graph = build_part_graph(assembled, "src/api", {"src/api/h.py"}, SCAN, "abc123")
    assert graph["part"] == "src/api"
    assert graph["project"]["name"] == "proj"
    assert graph["project"]["languages"] == ["python"]
    assert graph["project"]["gitCommitHash"] == "abc123"
    assert graph["layers"] == []


def test_adds_boundary_stub_for_cross_part_edge():
    assembled = {
        "nodes": [_node("file:src/api/h.py")],
        "edges": [
            {"source": "file:src/api/h.py", "target": "file:src/db/conn.py",
             "type": "imports", "weight": 0.7}
        ],
    }
    known = {"src/api/h.py", "src/db/conn.py"}
    graph = build_part_graph(assembled, "src/api", known, SCAN, "")
    stub = next(n for n in graph["nodes"] if n["id"] == "file:src/db/conn.py")
    assert stub["stub"] is True
