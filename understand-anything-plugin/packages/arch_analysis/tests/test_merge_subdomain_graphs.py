"""Tests for arch_analysis.merge_subdomain_graphs (tour-free port)."""

from __future__ import annotations

from arch_analysis.merge_subdomain_graphs import merge_graphs


def _graph(name, nodes, edges, layers=None, **proj):
    return {
        "version": "1.0.0",
        "project": {"name": name, "languages": [], "frameworks": [], "description": "", **proj},
        "nodes": nodes,
        "edges": edges,
        "layers": layers or [],
    }


def _node(nid):
    return {"id": nid, "type": "file", "name": nid, "summary": "", "tags": [], "complexity": "simple"}


def test_merges_nodes_and_dedupes():
    g1 = _graph("a", [_node("file:a"), _node("file:b")], [])
    g2 = _graph("a", [_node("file:b"), _node("file:c")], [])
    merged, _ = merge_graphs([g1, g2])
    ids = {n["id"] for n in merged["nodes"]}
    assert ids == {"file:a", "file:b", "file:c"}


def test_drops_dangling_edges():
    g = _graph(
        "a",
        [_node("file:a")],
        [{"source": "file:a", "target": "file:missing", "type": "imports", "weight": 0.5}],
    )
    merged, _ = merge_graphs([g])
    assert merged["edges"] == []


def test_merges_layers_union_nodeids():
    g1 = _graph("a", [_node("file:a"), _node("file:b")], [],
                layers=[{"id": "layer:x", "name": "X", "description": "d", "nodeIds": ["file:a"]}])
    g2 = _graph("a", [_node("file:b")], [],
                layers=[{"id": "layer:x", "name": "X", "description": "d", "nodeIds": ["file:b"]}])
    merged, _ = merge_graphs([g1, g2])
    layer = next(layer for layer in merged["layers"] if layer["id"] == "layer:x")
    assert set(layer["nodeIds"]) == {"file:a", "file:b"}


def test_output_has_no_tour_key_even_with_legacy_tour_input():
    g = _graph("a", [_node("file:a")], [])
    g["tour"] = [{"order": 1, "title": "x", "description": "y", "nodeIds": ["file:a"]}]
    merged, report = merge_graphs([g])
    assert "tour" not in merged
    assert not any("tour" in line.lower() for line in report)


def test_merges_project_metadata():
    g1 = _graph("proj", [_node("file:a")], [], languages=["python"], frameworks=["django"])
    g2 = _graph("proj", [_node("file:b")], [], languages=["typescript"], frameworks=["react"])
    merged, _ = merge_graphs([g1, g2])
    assert set(merged["project"]["languages"]) == {"python", "typescript"}
    assert set(merged["project"]["frameworks"]) == {"django", "react"}
