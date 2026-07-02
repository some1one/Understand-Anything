"""Deterministic knowledge-graph validation (graph-reviewer Phase 1).

Python port of the validation script the graph-reviewer agent used to author
inline. Validates an assembled graph and writes the review payload:

    { "scriptCompleted": true, "issues": [...], "warnings": [...], "stats": {...} }

Usage:
    python -m arch_analysis.validate_graph <graph.json> <review.json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Canonical type sets (superset covering structural + domain + knowledge graphs
# so valid knowledge/domain graphs are not rejected).
VALID_NODE_TYPES = frozenset(
    {
        "file", "function", "class", "module", "concept",
        "config", "document", "service", "table", "endpoint",
        "pipeline", "schema", "resource",
        "domain", "flow", "step",
        "article", "entity", "topic", "claim", "source",
    }
)

VALID_EDGE_TYPES = frozenset(
    {
        "imports", "exports", "contains", "inherits", "implements",
        "calls", "subscribes", "publishes", "middleware",
        "reads_from", "writes_to", "transforms", "validates",
        "depends_on", "tested_by", "configures",
        "related", "similar_to",
        "deploys", "serves", "provisions", "triggers",
        "migrates", "documents", "routes", "defines_schema",
        "contains_flow", "flow_step", "cross_domain",
        "cites", "contradicts", "builds_on", "exemplifies",
        "categorized_under", "authored_by",
    }
)

VALID_DIRECTIONS = frozenset({"forward", "backward", "bidirectional"})
VALID_COMPLEXITY = frozenset({"simple", "moderate", "complex"})

# File-level node types that must appear in exactly one layer (structural graphs).
FILE_LEVEL_TYPES = frozenset(
    {"file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"}
)

# Domain node types — presence flips the graph into "domain graph" mode.
DOMAIN_NODE_TYPES = frozenset({"domain", "flow", "step"})

# Expected-edge warnings for non-code node types (Check 7).
_EXPECTED_EDGE_BY_TYPE: dict[str, tuple[str, ...]] = {
    "document": ("documents",),
    "service": ("deploys", "depends_on"),
    "pipeline": ("triggers",),
    "table": ("migrates", "defines_schema"),
    "schema": ("defines_schema",),
    "domain": ("contains_flow",),
    "flow": ("flow_step",),
}


# Node-id prefixes whose second ``:``-segment is a project-relative file path.
_PATH_BEARING_PREFIXES = frozenset(
    {
        "file", "function", "class", "config", "document",
        "service", "table", "endpoint", "pipeline", "schema", "resource",
    }
)

_MAX_COVERAGE_WARNINGS = 50


def _node_file_path(node: dict[str, Any]) -> str | None:
    """The project-relative file path a node refers to, or None."""
    fp = node.get("filePath")
    if isinstance(fp, str) and fp:
        return fp
    nid = node.get("id", "")
    if not isinstance(nid, str):
        return None
    parts = nid.split(":")
    if len(parts) >= 2 and parts[0] in _PATH_BEARING_PREFIXES:
        return parts[1]
    return None


def load_scanned_paths(scan_result_path: Path) -> list[str]:
    """Read the file-path inventory from a ``scan-result.json``."""
    data = json.loads(scan_result_path.read_text(encoding="utf-8"))
    return [
        f["path"]
        for f in data.get("files", [])
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    ]


def add_scan_coverage(
    review: dict[str, Any], graph: dict[str, Any], scanned_paths: list[str]
) -> dict[str, Any]:
    """Cross-check graph node coverage against the scan inventory (mutates ``review``).

    Adds a warning for every scanned file with no corresponding node (possible
    data loss) and for every node whose file path is absent from the inventory
    (stale or invented reference), plus a ``coverage`` block in ``stats``.
    """
    nodes = graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []
    covered: set[str] = set()
    for n in nodes:
        if isinstance(n, dict):
            p = _node_file_path(n)
            if p:
                covered.add(p)

    scanned = set(scanned_paths)
    missing = sorted(scanned - covered)
    extra = sorted(covered - scanned)
    warnings = review["warnings"]

    for p in missing[:_MAX_COVERAGE_WARNINGS]:
        warnings.append(f"Scanned file '{p}' has no corresponding node in the graph")
    if len(missing) > _MAX_COVERAGE_WARNINGS:
        warnings.append(
            f"... and {len(missing) - _MAX_COVERAGE_WARNINGS} more scanned files with no node"
        )
    for p in extra[:_MAX_COVERAGE_WARNINGS]:
        warnings.append(f"Node references file '{p}' not present in the scan inventory")
    if len(extra) > _MAX_COVERAGE_WARNINGS:
        warnings.append(
            f"... and {len(extra) - _MAX_COVERAGE_WARNINGS} more nodes referencing unknown files"
        )

    review["stats"]["coverage"] = {
        "scannedFiles": len(scanned),
        "filesWithNodes": len(scanned & covered),
        "missingFileNodes": len(missing),
        "unknownFileNodes": len(extra),
    }
    return review


def review_graph(graph: dict[str, Any], require_layers: bool = True) -> dict[str, Any]:
    """Validate ``graph`` and return the review payload.

    ``require_layers=False`` is for the **pre-layer assembled graph** (the
    merge output, before the architecture-analyzer adds layers): it relaxes the
    zero-layers critical to a warning and skips the file-level layer-coverage
    check, while keeping every other check (schema fields, referential
    integrity, uniqueness, quality).
    """
    issues: list[str] = []
    warnings: list[str] = []

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    layers = graph.get("layers", [])

    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    if not isinstance(layers, list):
        layers = []

    is_domain_graph = any(n.get("type") in DOMAIN_NODE_TYPES for n in nodes if isinstance(n, dict))

    # --- Check 5: uniqueness ---
    id_positions: dict[str, list[int]] = {}
    for i, n in enumerate(nodes):
        if isinstance(n, dict) and n.get("id"):
            id_positions.setdefault(n["id"], []).append(i)
    for nid, positions in id_positions.items():
        if len(positions) > 1:
            issues.append(f"Duplicate node ID '{nid}' appears at indices {positions}")

    node_ids = set(id_positions.keys())

    # --- Check 1: node required fields ---
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            issues.append(f"Node at index {i} is not an object")
            continue
        nid = n.get("id")
        label = nid or n.get("name") or f"index {i}"
        if not nid or not isinstance(nid, str):
            issues.append(f"Node at index {i} ('{label}') missing required 'id'")
        ntype = n.get("type")
        if not ntype or not isinstance(ntype, str):
            issues.append(f"Node '{label}' missing required 'type'")
        elif ntype not in VALID_NODE_TYPES:
            issues.append(f"Node '{label}' has invalid type '{ntype}'")
        if not n.get("name") or not isinstance(n.get("name"), str):
            issues.append(f"Node '{label}' missing required 'name'")
        summary = n.get("summary")
        if not summary or not isinstance(summary, str):
            issues.append(f"Node '{label}' missing required 'summary'")
        elif summary == n.get("name") or summary == (n.get("filePath", "").rsplit("/", 1)[-1]):
            warnings.append(f"Node '{label}' has a generic summary")
        if not isinstance(n.get("tags"), list):
            issues.append(f"Node '{label}' missing required 'tags' array")
        complexity = n.get("complexity")
        if complexity not in VALID_COMPLEXITY:
            issues.append(f"Node '{label}' has invalid complexity '{complexity}'")

    # --- Check 1: edge required fields + Check 2: referential integrity ---
    degree: Counter[str] = Counter()
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            issues.append(f"Edge at index {i} is not an object")
            continue
        src, tgt = e.get("source"), e.get("target")
        etype = e.get("type")
        direction = e.get("direction")
        weight = e.get("weight")
        if not src or not isinstance(src, str):
            issues.append(f"Edge at index {i} missing required 'source'")
        elif src not in node_ids:
            issues.append(f"Edge at index {i} references non-existent source node '{src}'")
        if not tgt or not isinstance(tgt, str):
            issues.append(f"Edge at index {i} missing required 'target'")
        elif tgt not in node_ids:
            issues.append(f"Edge at index {i} references non-existent target node '{tgt}'")
        if etype not in VALID_EDGE_TYPES:
            issues.append(f"Edge at index {i} has invalid type '{etype}'")
        if direction not in VALID_DIRECTIONS:
            issues.append(f"Edge at index {i} has invalid direction '{direction}'")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not (0.0 <= weight <= 1.0):
            issues.append(f"Edge at index {i} has weight outside 0.0-1.0: {weight!r}")
        if isinstance(src, str) and isinstance(tgt, str):
            if src == tgt:
                warnings.append(f"Edge at index {i} is self-referencing ('{src}')")
            degree[src] += 1
            degree[tgt] += 1

    # --- Check 2 (layers) + Check 4: layer coverage ---
    node_to_layers: dict[str, list[str]] = {}
    for li, layer in enumerate(layers):
        if not isinstance(layer, dict):
            issues.append(f"Layer at index {li} is not an object")
            continue
        layer_ids = layer.get("nodeIds", [])
        if not isinstance(layer_ids, list) or len(layer_ids) == 0:
            issues.append(f"Layer '{layer.get('id', li)}' has an empty nodeIds array")
            continue
        for nid in layer_ids:
            if nid not in node_ids:
                issues.append(
                    f"Layer '{layer.get('id', li)}' references non-existent node '{nid}'"
                )
            else:
                node_to_layers.setdefault(nid, []).append(str(layer.get("id", li)))

    # --- Check 3: completeness ---
    if len(nodes) == 0:
        issues.append("Graph has zero nodes")
    if len(edges) == 0:
        issues.append("Graph has zero edges")
    if len(layers) == 0:
        if is_domain_graph:
            warnings.append("Domain graph has zero layers (relaxed to warning)")
        elif not require_layers:
            warnings.append("Assembled graph has zero layers (pre-layer stage — relaxed to warning)")
        else:
            issues.append("Graph has zero layers")

    # Check 4: file-level nodes must appear in exactly one layer (structural only).
    if require_layers and not (is_domain_graph and len(layers) == 0):
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if n.get("type") in FILE_LEVEL_TYPES and n.get("id"):
                appearances = node_to_layers.get(n["id"], [])
                if len(appearances) == 0:
                    issues.append(
                        f"File-level node '{n['id']}' is missing from all layers"
                    )
                elif len(appearances) > 1:
                    issues.append(
                        f"File-level node '{n['id']}' appears in multiple layers: {appearances}"
                    )

    # --- Check 6: orphan nodes (warning) ---
    for n in nodes:
        if isinstance(n, dict) and n.get("id") and degree[n["id"]] == 0:
            warnings.append(f"Orphan node '{n['id']}' has no connecting edges")

    # --- Check 7: expected non-code edges (warning) ---
    out_edge_types_by_node: dict[str, set[str]] = {}
    for e in edges:
        if isinstance(e, dict) and isinstance(e.get("source"), str) and isinstance(e.get("type"), str):
            out_edge_types_by_node.setdefault(e["source"], set()).add(e["type"])
            if isinstance(e.get("target"), str):
                out_edge_types_by_node.setdefault(e["target"], set()).add(e["type"])
    for n in nodes:
        if not isinstance(n, dict):
            continue
        expected = _EXPECTED_EDGE_BY_TYPE.get(n.get("type", ""))
        if expected and n.get("id"):
            present = out_edge_types_by_node.get(n["id"], set())
            if not any(t in present for t in expected):
                warnings.append(
                    f"{n['type'].capitalize()} node '{n['id']}' has no "
                    f"{' or '.join(expected)} edges"
                )

    # --- Check 8: type / ID prefix consistency (warning) ---
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid, ntype = n.get("id"), n.get("type")
        if isinstance(nid, str) and isinstance(ntype, str) and ":" in nid:
            prefix = nid.split(":", 1)[0]
            if prefix != ntype:
                warnings.append(
                    f"Node '{nid}' type '{ntype}' does not match ID prefix '{prefix}:'"
                )

    stats = {
        "totalNodes": len(nodes),
        "totalEdges": len(edges),
        "totalLayers": len(layers),
        "nodeTypes": dict(
            Counter(n.get("type") for n in nodes if isinstance(n, dict) and n.get("type"))
        ),
        "edgeTypes": dict(
            Counter(e.get("type") for e in edges if isinstance(e, dict) and e.get("type"))
        ),
    }

    return {
        "scriptCompleted": True,
        "issues": issues,
        "warnings": warnings,
        "stats": stats,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    positional: list[str] = []
    scan_result: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--scan-result" and i + 1 < len(args):
            scan_result = args[i + 1]
            i += 2
            continue
        if arg.startswith("--scan-result="):
            scan_result = arg.split("=", 1)[1]
            i += 1
            continue
        positional.append(arg)
        i += 1

    if len(positional) < 2:
        sys.stderr.write(
            "Usage: python -m arch_analysis.validate_graph <graph.json> <review.json> "
            "[--scan-result <scan-result.json>]\n"
        )
        return 1

    graph_path, review_path = positional[0], positional[1]
    try:
        graph = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"validate_graph failed: cannot read {graph_path}: {err}\n")
        return 1

    review = review_graph(graph)
    if scan_result is not None:
        try:
            add_scan_coverage(review, graph, load_scanned_paths(Path(scan_result)))
        except (OSError, json.JSONDecodeError) as err:
            sys.stderr.write(
                f"validate_graph: scan-coverage skipped — cannot read {scan_result}: {err}\n"
            )
    Path(review_path).write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")

    sys.stderr.write(
        f"validate_graph: {len(review['issues'])} issues, {len(review['warnings'])} warnings "
        f"({review['stats']['totalNodes']} nodes, {review['stats']['totalEdges']} edges)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
