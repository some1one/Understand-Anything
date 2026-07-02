"""Deterministic domain-graph validation.

Validates a domain knowledge graph (nodes of type ``domain``/``flow``/``step``)
in three layers:

  1. The shared :func:`arch_analysis.validate_graph.review_graph` structural
     checks (referential integrity, uniqueness, weights, required fields — with
     the layers requirement relaxed for domain graphs).
  2. Domain-specific checks: domain-only node/edge types, ``contains_flow`` /
     ``flow_step`` coverage, valid ``cross_domain`` edges, empty layers, and
     monotonic ``flow_step`` weights per flow.
  3. JSON Schema validation against ``domain-graph.schema.json``.

Writes the combined review payload (``scriptCompleted``, ``issues``,
``warnings``, ``stats``) and always exits ``0`` unless the file cannot be read.

Usage:
    python -m arch_analysis.validate_domain_graph <domain-graph.json> [review.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import schema as schema_mod
from .validate_graph import review_graph

DOMAIN_NODE_TYPES = frozenset({"domain", "flow", "step"})
DOMAIN_EDGE_TYPES = frozenset({"contains_flow", "flow_step", "cross_domain"})


def review_domain_graph(graph: dict[str, Any]) -> dict[str, Any]:
    review = review_graph(graph)
    issues = review["issues"]

    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    edges = [e for e in graph.get("edges", []) if isinstance(e, dict)]
    layers = graph.get("layers", [])

    node_type: dict[str, str] = {
        n["id"]: n.get("type") for n in nodes if isinstance(n.get("id"), str)
    }

    if not any(n.get("type") == "domain" for n in nodes):
        issues.append("Domain graph has zero 'domain' nodes")

    # ── Domain-only node / edge types ────────────────────────────────────
    for n in nodes:
        t = n.get("type")
        if t not in DOMAIN_NODE_TYPES:
            issues.append(
                f"Node '{n.get('id')}' has non-domain type '{t}' "
                f"(allowed: domain, flow, step)"
            )
    for i, e in enumerate(edges):
        t = e.get("type")
        if t not in DOMAIN_EDGE_TYPES:
            issues.append(
                f"Edge at index {i} has non-domain type '{t}' "
                f"(allowed: contains_flow, flow_step, cross_domain)"
            )

    # ── Hierarchy coverage + cross_domain validity ──────────────────────
    flows_with_domain: set[str] = set()
    steps_with_flow: set[str] = set()
    for e in edges:
        src, tgt, etype = e.get("source"), e.get("target"), e.get("type")
        if etype == "contains_flow":
            if node_type.get(src) != "domain":
                issues.append(
                    f"contains_flow edge {src} → {tgt} must originate from a domain node"
                )
            if node_type.get(tgt) == "flow":
                flows_with_domain.add(tgt)
        elif etype == "flow_step":
            if node_type.get(src) != "flow":
                issues.append(
                    f"flow_step edge {src} → {tgt} must originate from a flow node"
                )
            if node_type.get(tgt) == "step":
                steps_with_flow.add(tgt)
        elif etype == "cross_domain":
            if node_type.get(src) != "domain" or node_type.get(tgt) != "domain":
                issues.append(
                    f"cross_domain edge {src} → {tgt} must connect two domain nodes"
                )

    for n in nodes:
        nid = n.get("id")
        if n.get("type") == "flow" and nid not in flows_with_domain:
            issues.append(
                f"Flow '{nid}' is not connected to any domain via a contains_flow edge"
            )
        if n.get("type") == "step" and nid not in steps_with_flow:
            issues.append(
                f"Step '{nid}' is not connected to any flow via a flow_step edge"
            )

    # ── Layers must be empty for domain graphs ──────────────────────────
    if isinstance(layers, list) and len(layers) > 0:
        issues.append(
            f"Domain graph must have empty layers (found {len(layers)} layer(s))"
        )

    # ── Monotonic flow_step weights per flow (array order) ──────────────
    per_flow_weights: dict[str, list[Any]] = {}
    for e in edges:
        if e.get("type") == "flow_step":
            per_flow_weights.setdefault(e.get("source"), []).append(e.get("weight"))
    for flow_id, weights in per_flow_weights.items():
        prev: float | None = None
        for w in weights:
            if not isinstance(w, (int, float)) or isinstance(w, bool):
                continue
            if prev is not None and w < prev:
                issues.append(
                    f"Flow '{flow_id}' has non-monotonic flow_step weights: {weights}"
                )
                break
            prev = w

    # ── JSON Schema validation ───────────────────────────────────────────
    try:
        schema_mod.validate_domain_graph(graph)
    except schema_mod.SchemaValidationError as err:
        issues.append(f"schema validation: {err}")

    return review


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.validate_domain_graph "
            "<domain-graph.json> [review.json]\n"
        )
        return 1

    graph_path = Path(args[0])
    review_path = (
        Path(args[1]) if len(args) > 1 else graph_path.with_name("domain-review.json")
    )

    try:
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(
            f"validate_domain_graph failed: cannot read {graph_path}: {err}\n"
        )
        return 1

    review = review_domain_graph(graph)
    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    sys.stderr.write(
        f"validate_domain_graph: {len(review['issues'])} issues, "
        f"{len(review['warnings'])} warnings\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
