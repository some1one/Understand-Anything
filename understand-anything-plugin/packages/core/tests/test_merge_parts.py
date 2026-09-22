"""Tests for understand_core.merge_parts and select_partition_graphs."""

from __future__ import annotations

import json
from pathlib import Path

from understand_core.merge_parts import main as merge_parts_main
from understand_core.merge_subdomain_graphs import select_partition_graphs


def _node(nid, stub=False):
    node = {"id": nid, "type": "file", "name": nid, "summary": "s", "tags": [], "complexity": "simple"}
    if stub:
        node["stub"] = True
    return node


def _part_graph(part, nodes, edges):
    return {
        "version": "1.0.0",
        "part": part,
        "project": {"name": "p", "languages": [], "frameworks": [], "description": "",
                    "analyzedAt": "", "gitCommitHash": ""},
        "nodes": nodes,
        "edges": edges,
        "layers": [],
    }


def _write(ua: Path, part: str, graph: dict) -> None:
    (ua / "partitions").mkdir(parents=True, exist_ok=True)
    (ua / "partitions" / f"{part.replace('/', '~')}.knowledge-graph.json").write_text(
        json.dumps(graph), encoding="utf-8"
    )


def _setup(tmp_path: Path):
    ua = tmp_path / ".understand-anything"
    # Part api imports db (stub); part db defines the real node.
    _write(ua, "api", _part_graph(
        "api",
        [_node("file:src/api/h.py"), _node("file:src/db/conn.py", stub=True)],
        [{"source": "file:src/api/h.py", "target": "file:src/db/conn.py", "type": "imports", "weight": 0.7}],
    ))
    _write(ua, "db", _part_graph("db", [_node("file:src/db/conn.py")], []))
    return ua


def test_merges_parts_resolving_stub_and_preserving_edge(tmp_path):
    _setup(tmp_path)
    rc = merge_parts_main([str(tmp_path)])
    assert rc == 0
    merged = json.loads(
        (tmp_path / ".understand-anything" / "intermediate" / "assembled-graph.json").read_text()
    )
    ids = {n["id"] for n in merged["nodes"]}
    assert ids == {"file:src/api/h.py", "file:src/db/conn.py"}
    # cross-part edge survived
    assert len(merged["edges"]) == 1
    # real node beat the stub
    conn = next(n for n in merged["nodes"] if n["id"] == "file:src/db/conn.py")
    assert not conn.get("stub")


def test_included_parts_filter(tmp_path):
    ua = _setup(tmp_path)
    ua.mkdir(parents=True, exist_ok=True)
    (ua / "config.json").write_text(json.dumps({"includedParts": ["api"]}))
    selected = {p.name for p in select_partition_graphs(tmp_path)}
    assert selected == {"api.knowledge-graph.json"}
