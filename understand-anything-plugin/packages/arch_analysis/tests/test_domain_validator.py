"""Tests for the upgraded arch_analysis.validate_domain_graph reviewer."""

from __future__ import annotations

from arch_analysis.validate_domain_graph import review_domain_graph


def _node(nid, ntype, **extra):
    n = {
        "id": nid,
        "type": ntype,
        "name": nid.split(":")[-1],
        "summary": f"Summary of {nid}.",
        "tags": ["x"],
        "complexity": "simple",
    }
    n.update(extra)
    return n


def _edge(src, tgt, etype, weight=0.5):
    return {"source": src, "target": tgt, "type": etype, "direction": "forward", "weight": weight}


def _valid_domain_graph():
    return {
        "version": "1.0.0",
        "project": {
            "name": "demo",
            "languages": ["python"],
            "frameworks": [],
            "description": "A demo.",
            "analyzedAt": "2026-01-01T00:00:00Z",
            "gitCommitHash": "abc123",
        },
        "nodes": [
            _node("domain:billing", "domain"),
            _node("flow:checkout", "flow"),
            _node("step:checkout:validate", "step"),
            _node("step:checkout:charge", "step"),
        ],
        "edges": [
            _edge("domain:billing", "flow:checkout", "contains_flow", 1.0),
            _edge("flow:checkout", "step:checkout:validate", "flow_step", 0.1),
            _edge("flow:checkout", "step:checkout:charge", "flow_step", 0.2),
        ],
        "layers": [],
    }


def test_valid_domain_graph_has_no_issues():
    review = review_domain_graph(_valid_domain_graph())
    assert review["issues"] == [], review["issues"]


def test_missing_domain_node():
    g = _valid_domain_graph()
    g["nodes"] = [n for n in g["nodes"] if n["type"] != "domain"]
    g["edges"] = [e for e in g["edges"] if e["type"] != "contains_flow"]
    review = review_domain_graph(g)
    assert any("zero 'domain' nodes" in i for i in review["issues"])


def test_flow_without_domain():
    g = _valid_domain_graph()
    g["edges"] = [e for e in g["edges"] if e["type"] != "contains_flow"]
    review = review_domain_graph(g)
    assert any("not connected to any domain" in i for i in review["issues"])


def test_step_without_flow():
    g = _valid_domain_graph()
    g["edges"] = [e for e in g["edges"] if not (e["type"] == "flow_step" and e["target"] == "step:checkout:charge")]
    review = review_domain_graph(g)
    assert any("step:checkout:charge" in i and "not connected to any flow" in i for i in review["issues"])


def test_invalid_edge_type():
    g = _valid_domain_graph()
    g["edges"].append(_edge("domain:billing", "flow:checkout", "imports"))
    review = review_domain_graph(g)
    assert any("non-domain type 'imports'" in i for i in review["issues"])


def test_non_empty_layers():
    g = _valid_domain_graph()
    g["layers"] = [{"id": "layer:x", "name": "X", "description": "d", "nodeIds": ["domain:billing"]}]
    review = review_domain_graph(g)
    assert any("must have empty layers" in i for i in review["issues"])


def test_non_monotonic_flow_step_weights():
    g = _valid_domain_graph()
    # charge (0.05) comes after validate (0.1) in array order → decreasing.
    for e in g["edges"]:
        if e["type"] == "flow_step" and e["target"] == "step:checkout:charge":
            e["weight"] = 0.05
    review = review_domain_graph(g)
    assert any("non-monotonic flow_step weights" in i for i in review["issues"])


def test_cross_domain_must_connect_domains():
    g = _valid_domain_graph()
    g["nodes"].append(_node("domain:ledger", "domain"))
    g["edges"].append(_edge("domain:billing", "domain:ledger", "cross_domain", 0.6))
    # valid cross_domain — no issue about cross_domain
    review = review_domain_graph(g)
    assert not any("must connect two domain nodes" in i for i in review["issues"])
    # now make it point at a flow
    g["edges"][-1]["target"] = "flow:checkout"
    review2 = review_domain_graph(g)
    assert any("must connect two domain nodes" in i for i in review2["issues"])
