"""Port of packages/core/src/__tests__/domain-types.test.ts."""

from __future__ import annotations

import copy

from understand_core.schema import validate_graph

DOMAIN_GRAPH = {
    "version": "1.0.0",
    "project": {
        "name": "test-project",
        "languages": ["typescript"],
        "frameworks": [],
        "description": "A test project",
        "analyzedAt": "2026-04-01T00:00:00.000Z",
        "gitCommitHash": "abc123",
    },
    "nodes": [
        {
            "id": "domain:order-management",
            "type": "domain",
            "name": "Order Management",
            "summary": "Handles order lifecycle",
            "tags": ["core"],
            "complexity": "complex",
        },
        {
            "id": "flow:create-order",
            "type": "flow",
            "name": "Create Order",
            "summary": "Customer submits a new order",
            "tags": ["write-path"],
            "complexity": "moderate",
            "domainMeta": {"entryPoint": "POST /api/orders", "entryType": "http"},
        },
        {
            "id": "step:create-order:validate",
            "type": "step",
            "name": "Validate Input",
            "summary": "Checks request body",
            "tags": ["validation"],
            "complexity": "simple",
            "filePath": "src/validators/order.ts",
            "lineRange": [10, 30],
        },
    ],
    "edges": [
        {"source": "domain:order-management", "target": "flow:create-order", "type": "contains_flow", "direction": "forward", "weight": 1.0},
        {"source": "flow:create-order", "target": "step:create-order:validate", "type": "flow_step", "direction": "forward", "weight": 0.1},
    ],
    "layers": [],
}


def clone():
    return copy.deepcopy(DOMAIN_GRAPH)


def test_validates_domain_graph():
    result = validate_graph(DOMAIN_GRAPH)
    assert result["success"] is True
    assert result["data"] is not None
    assert len(result["data"]["nodes"]) == 3
    assert len(result["data"]["edges"]) == 2


def test_validates_contains_flow_edge():
    result = validate_graph(DOMAIN_GRAPH)
    assert result["success"] is True
    assert result["data"]["edges"][0]["type"] == "contains_flow"


def test_validates_flow_step_edge():
    result = validate_graph(DOMAIN_GRAPH)
    assert result["success"] is True
    assert result["data"]["edges"][1]["type"] == "flow_step"


def test_validates_cross_domain_edge():
    graph = clone()
    graph["nodes"].append({
        "id": "domain:logistics", "type": "domain", "name": "Logistics",
        "summary": "Handles shipping", "tags": [], "complexity": "moderate",
    })
    graph["edges"].append({
        "source": "domain:order-management", "target": "domain:logistics",
        "type": "cross_domain", "direction": "forward",
        "description": "Triggers on order confirmed", "weight": 0.6,
    })
    result = validate_graph(graph)
    assert result["success"] is True


def test_normalizes_domain_type_aliases():
    graph = clone()
    graph["nodes"][0]["type"] = "business_domain"
    graph["nodes"][1]["type"] = "business_flow"
    graph["nodes"][2]["type"] = "business_step"
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["nodes"][0]["type"] == "domain"
    assert result["data"]["nodes"][1]["type"] == "flow"
    assert result["data"]["nodes"][2]["type"] == "step"


def test_normalizes_domain_edge_aliases():
    graph = clone()
    graph["edges"][0]["type"] = "has_flow"
    graph["edges"][1]["type"] = "next_step"
    result = validate_graph(graph)
    assert result["success"] is True
    assert result["data"]["edges"][0]["type"] == "contains_flow"
    assert result["data"]["edges"][1]["type"] == "flow_step"


def test_preserves_domain_meta():
    result = validate_graph(DOMAIN_GRAPH)
    assert result["success"] is True
    flow_node = next(n for n in result["data"]["nodes"] if n["id"] == "flow:create-order")
    assert flow_node["domainMeta"] == {"entryPoint": "POST /api/orders", "entryType": "http"}
