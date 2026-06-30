"""Tests for validate_graph, validate_domain_graph, generate_ignore, domain context."""

from __future__ import annotations

from arch_analysis.validate_graph import review_graph
from arch_analysis.validate_domain_graph import review_domain_graph
from arch_analysis.generate_ignore import generate_starter_ignore_file


def _node(nid, ntype="file", **extra):
    n = {
        "id": nid,
        "type": ntype,
        "name": nid.split(":")[-1],
        "summary": f"Does {nid}",
        "tags": ["x"],
        "complexity": "simple",
    }
    n.update(extra)
    return n


def _edge(src, tgt, etype="imports"):
    return {"source": src, "target": tgt, "type": etype, "direction": "forward", "weight": 0.5}


def _valid_graph():
    return {
        "nodes": [_node("file:a.ts"), _node("file:b.ts")],
        "edges": [_edge("file:a.ts", "file:b.ts")],
        "layers": [{"id": "layer:core", "name": "Core", "description": "d", "nodeIds": ["file:a.ts", "file:b.ts"]}],
    }


def test_valid_graph_has_no_issues():
    review = review_graph(_valid_graph())
    assert review["scriptCompleted"] is True
    assert review["issues"] == []
    assert review["stats"]["totalNodes"] == 2
    assert review["stats"]["totalEdges"] == 1
    assert review["stats"]["nodeTypes"]["file"] == 2


def test_dangling_edge_is_critical():
    g = _valid_graph()
    g["edges"].append(_edge("file:a.ts", "file:missing.ts"))
    review = review_graph(g)
    assert any("non-existent target" in i for i in review["issues"])


def test_duplicate_node_id_is_critical():
    g = _valid_graph()
    g["nodes"].append(_node("file:a.ts"))
    review = review_graph(g)
    assert any("Duplicate node ID" in i for i in review["issues"])


def test_invalid_weight_is_critical():
    g = _valid_graph()
    g["edges"][0]["weight"] = 1.7
    review = review_graph(g)
    assert any("weight outside" in i for i in review["issues"])


def test_file_level_node_missing_from_layers_is_critical():
    g = _valid_graph()
    g["layers"][0]["nodeIds"] = ["file:a.ts"]  # drop file:b.ts
    review = review_graph(g)
    assert any("missing from all layers" in i for i in review["issues"])


def test_orphan_node_is_warning():
    g = _valid_graph()
    g["nodes"].append(_node("file:c.ts"))
    g["layers"][0]["nodeIds"].append("file:c.ts")
    review = review_graph(g)
    assert any("Orphan node 'file:c.ts'" in w for w in review["warnings"])


def test_zero_layers_critical_for_structural_graph():
    g = _valid_graph()
    g["layers"] = []
    review = review_graph(g)
    assert any("zero layers" in i for i in review["issues"])


def test_domain_graph_relaxes_layers():
    g = {
        "nodes": [_node("domain:billing", "domain"), _node("flow:checkout", "flow")],
        "edges": [_edge("domain:billing", "flow:checkout", "contains_flow")],
        "layers": [],
    }
    review = review_graph(g)
    # Zero layers is a warning (not a critical issue) for domain graphs.
    assert not any("zero layers" in i for i in review["issues"])
    assert any("zero layers" in w for w in review["warnings"])


def test_domain_validator_requires_domain_node():
    g = {
        "nodes": [_node("flow:checkout", "flow")],
        "edges": [],
        "layers": [],
    }
    review = review_domain_graph(g)
    assert any("zero 'domain' nodes" in i for i in review["issues"])


def test_type_prefix_mismatch_warning():
    g = _valid_graph()
    g["nodes"][0] = _node("config:a.ts", "file")  # prefix config, type file
    g["layers"][0]["nodeIds"] = ["config:a.ts", "file:b.ts"]
    review = review_graph(g)
    assert any("does not match ID prefix" in w for w in review["warnings"])


# --- generate_ignore ---


def test_generate_ignore_emits_commented_suggestions(tmp_path):
    (tmp_path / ".gitignore").write_text("custom_dir/\nnode_modules/\n")
    (tmp_path / "tests").mkdir()
    content = generate_starter_ignore_file(tmp_path)
    # Header + sections present.
    assert ".understandignore" in content
    # gitignore pattern not covered by defaults is suggested (commented).
    assert "# custom_dir/" in content
    # node_modules/ IS a default → excluded from the suggestions.
    assert "# node_modules/" not in content
    # detected tests/ directory suggested.
    assert "# tests/" in content
    # test pattern groups present.
    assert "*.test.*" in content
    # All non-header lines are commented or blank.
    for line in content.splitlines():
        assert line == "" or line.startswith("#")
