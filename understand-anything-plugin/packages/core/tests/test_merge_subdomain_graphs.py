"""Tests for understand_core.merge_subdomain_graphs (tour-free port)."""

from __future__ import annotations

from understand_core.merge_subdomain_graphs import (
    discover_partition_graphs,
    merge_graphs,
)


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


def _stub(nid):
    node = _node(nid)
    node["stub"] = True
    node["summary"] = "external"
    return node


def test_real_node_beats_stub_regardless_of_order():
    # Stub first, real second.
    g1 = _graph("a", [_stub("file:shared")], [])
    g2 = _graph("a", [_node("file:shared")], [])
    merged, _ = merge_graphs([g1, g2])
    node = next(n for n in merged["nodes"] if n["id"] == "file:shared")
    assert not node.get("stub")

    # Real first, stub second — real still wins.
    merged2, _ = merge_graphs([g2, g1])
    node2 = next(n for n in merged2["nodes"] if n["id"] == "file:shared")
    assert not node2.get("stub")


def test_cross_part_edge_survives_via_stub_then_real():
    # Part A has a stub for a node that Part B actually defines; the edge must
    # survive the merge and point at the real node.
    part_a = _graph(
        "a",
        [_node("file:a"), _stub("file:b")],
        [{"source": "file:a", "target": "file:b", "type": "imports", "weight": 0.7}],
    )
    part_b = _graph("a", [_node("file:b")], [])
    merged, _ = merge_graphs([part_a, part_b])
    assert len(merged["edges"]) == 1
    ids = {n["id"] for n in merged["nodes"]}
    assert ids == {"file:a", "file:b"}
    assert not next(n for n in merged["nodes"] if n["id"] == "file:b").get("stub")


def test_discover_partition_graphs(tmp_path):
    ua = tmp_path / ".understand-anything"
    (ua / "partitions").mkdir(parents=True)
    (ua / "knowledge-graph.json").write_text("{}")  # merged output — excluded
    (ua / "legacy.knowledge-graph.json").write_text("{}")  # root legacy — included
    (ua / "partitions" / "src.knowledge-graph.json").write_text("{}")
    (ua / "partitions" / "api.knowledge-graph.json").write_text("{}")
    found = {p.name for p in discover_partition_graphs(ua)}
    assert found == {
        "legacy.knowledge-graph.json",
        "src.knowledge-graph.json",
        "api.knowledge-graph.json",
    }
