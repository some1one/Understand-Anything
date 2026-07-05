"""Knowledge-graph validation — port of ``packages/core/src/schema.ts``.

This is the tiered, repair-oriented validator the dashboard uses on graph load
(sanitize -> normalize aliases -> auto-fix defaults -> per-item validate with
drop). It is *not* the same as :mod:`arch_analysis.schema`, which renders strict
JSON Schemas; that module rejects, this one repairs. We port the TS behaviour
faithfully and keep the same issue/category strings the tests assert.

zod schemas become pydantic models; ``Schema.safeParse`` becomes a try/except
around ``Model.model_validate``.
"""

from __future__ import annotations

import math
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# ---------------------------------------------------------------------------
# Enum value sets
# ---------------------------------------------------------------------------
# The canonical type taxonomy lives in arch_analysis.constants (shared with the
# strict validator arch_analysis.validate_graph) so it is defined once.
from arch_analysis.constants import (  # noqa: E402
    VALID_COMPLEXITY as _COMPLEXITIES,
    VALID_DIRECTIONS as _DIRECTIONS,
    VALID_EDGE_TYPES as _EDGE_TYPES,
    VALID_NODE_TYPES as _NODE_TYPES,
)


# Aliases that LLMs commonly generate instead of canonical node types.
NODE_TYPE_ALIASES: dict[str, str] = {
    "func": "function",
    "fn": "function",
    "method": "function",
    "interface": "class",
    "struct": "class",
    "mod": "module",
    "pkg": "module",
    "package": "module",
    # Non-code aliases
    "container": "service",
    "deployment": "service",
    "pod": "service",
    "doc": "document",
    "readme": "document",
    "docs": "document",
    "job": "pipeline",
    "ci": "pipeline",
    "route": "endpoint",
    "api": "endpoint",
    "query": "endpoint",
    "mutation": "endpoint",
    "setting": "config",
    "env": "config",
    "configuration": "config",
    "infra": "resource",
    "infrastructure": "resource",
    "terraform": "resource",
    "migration": "table",
    "database": "table",
    "db": "table",
    "view": "table",
    "proto": "schema",
    "protobuf": "schema",
    "definition": "schema",
    "typedef": "schema",
    # Domain aliases — "process" intentionally excluded (ambiguous)
    "business_domain": "domain",
    "business_flow": "flow",
    "business_process": "flow",
    "task": "step",
    "business_step": "step",
    # Knowledge aliases
    "note": "article",
    "page": "article",
    "wiki_page": "article",
    "person": "entity",
    "actor": "entity",
    "organization": "entity",
    "tag": "topic",
    "category": "topic",
    "theme": "topic",
    "assertion": "claim",
    "decision": "claim",
    "thesis": "claim",
    "reference": "source",
    "raw": "source",
    "paper": "source",
}

# Aliases that LLMs commonly generate instead of canonical edge types.
EDGE_TYPE_ALIASES: dict[str, str] = {
    "extends": "inherits",
    "invokes": "calls",
    "invoke": "calls",
    "uses": "depends_on",
    "requires": "depends_on",
    "relates_to": "related",
    "related_to": "related",
    "similar": "similar_to",
    "import": "imports",
    "export": "exports",
    "contain": "contains",
    "publish": "publishes",
    "subscribe": "subscribes",
    # Non-code aliases
    "describes": "documents",
    "documented_by": "documents",
    "creates": "provisions",
    "exposes": "serves",
    "listens": "serves",
    "deploys_to": "deploys",
    "migrates_to": "migrates",
    "routes_to": "routes",
    "triggers_on": "triggers",
    "fires": "triggers",
    "defines": "defines_schema",
    # Domain aliases
    "has_flow": "contains_flow",
    "next_step": "flow_step",
    "interacts_with": "cross_domain",
    # Knowledge aliases
    "references": "cites",
    "cites_source": "cites",
    "conflicts_with": "contradicts",
    "disagrees_with": "contradicts",
    "refines": "builds_on",
    "elaborates": "builds_on",
    "illustrates": "exemplifies",
    "instance_of": "exemplifies",
    "example_of": "exemplifies",
    "belongs_to": "categorized_under",
    "tagged_with": "categorized_under",
    "written_by": "authored_by",
    "created_by": "authored_by",
    # Note: "implemented_by" is intentionally NOT aliased to "implements" — it
    # inverts edge direction. The LLM should use "implements" with correct
    # source/target instead.
}

# Aliases for complexity values LLMs commonly generate.
COMPLEXITY_ALIASES: dict[str, str] = {
    "low": "simple",
    "easy": "simple",
    "medium": "moderate",
    "intermediate": "moderate",
    "high": "complex",
    "hard": "complex",
    "difficult": "complex",
}

# Aliases for direction values LLMs commonly generate.
DIRECTION_ALIASES: dict[str, str] = {
    "to": "forward",
    "outbound": "forward",
    "from": "backward",
    "inbound": "backward",
    "both": "bidirectional",
    "mutual": "bidirectional",
}


# ---------------------------------------------------------------------------
# Issue / result shapes
# ---------------------------------------------------------------------------


class GraphIssue(TypedDict, total=False):
    level: Literal["auto-corrected", "dropped", "fatal"]
    category: str
    message: str
    path: str


class ValidationResult(TypedDict, total=False):
    success: bool
    data: dict[str, Any]
    errors: list[str]
    issues: list[GraphIssue]
    fatal: str


# ---------------------------------------------------------------------------
# Pydantic validation models (mirror the zod schemas in schema.ts)
# ---------------------------------------------------------------------------


class _GraphNodeModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal[
        "file", "function", "class", "module", "concept",
        "config", "document", "service", "table", "endpoint",
        "pipeline", "schema", "resource",
        "domain", "flow", "step",
        "article", "entity", "topic", "claim", "source",
    ]
    name: str
    filePath: str | None = None
    lineRange: list | None = None
    summary: str
    tags: list[str]
    complexity: Literal["simple", "moderate", "complex"]
    languageNotes: str | None = None
    domainMeta: dict[str, Any] | None = None
    knowledgeMeta: dict[str, Any] | None = None


class _GraphEdgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    type: str
    direction: Literal["forward", "backward", "bidirectional"]
    description: str | None = None
    weight: float = Field(ge=0.0, le=1.0)

    @field_validator("type")
    @classmethod
    def _check_edge_type(cls, v: str) -> str:
        if v not in _EDGE_TYPES:
            raise ValueError("invalid edge type")
        return v


class _LayerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    nodeIds: list[str]


class _ProjectMetaModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    languages: list[str]
    frameworks: list[str]
    description: str
    analyzedAt: str
    gitCommitHash: str


def _first_error_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if errors:
        return errors[0].get("msg", "validation failed")
    return "validation failed"


# ---------------------------------------------------------------------------
# Tier 1 — sanitize
# ---------------------------------------------------------------------------


def sanitize_graph(data: dict[str, Any]) -> dict[str, Any]:
    """Null -> empty/undefined coercion + enum-string lowercasing."""
    result = dict(data)

    if data.get("layers") is None:
        result["layers"] = []

    nodes = data.get("nodes")
    if isinstance(nodes, list):
        new_nodes: list[Any] = []
        for node in nodes:
            if not isinstance(node, dict):
                new_nodes.append(node)
                continue
            n = dict(node)
            if n.get("filePath") is None:
                n.pop("filePath", None)
            if n.get("lineRange") is None:
                n.pop("lineRange", None)
            if n.get("languageNotes") is None:
                n.pop("languageNotes", None)
            if isinstance(n.get("type"), str):
                n["type"] = n["type"].lower()
            if isinstance(n.get("complexity"), str):
                n["complexity"] = n["complexity"].lower()
            new_nodes.append(n)
        result["nodes"] = new_nodes

    edges = data.get("edges")
    if isinstance(edges, list):
        new_edges: list[Any] = []
        for edge in edges:
            if not isinstance(edge, dict):
                new_edges.append(edge)
                continue
            e = dict(edge)
            if e.get("description") is None:
                e.pop("description", None)
            if isinstance(e.get("type"), str):
                e["type"] = e["type"].lower()
            if isinstance(e.get("direction"), str):
                e["direction"] = e["direction"].lower()
            new_edges.append(e)
        result["edges"] = new_edges

    return result


# ---------------------------------------------------------------------------
# Normalize aliases
# ---------------------------------------------------------------------------


def normalize_graph(data: Any) -> Any:
    """Map alias node/edge types to canonical types."""
    if not isinstance(data, dict):
        return data

    result = dict(data)

    nodes = data.get("nodes")
    if isinstance(nodes, list):
        new_nodes: list[Any] = []
        for node in nodes:
            if (
                isinstance(node, dict)
                and isinstance(node.get("type"), str)
                and node["type"] in NODE_TYPE_ALIASES
            ):
                new_nodes.append({**node, "type": NODE_TYPE_ALIASES[node["type"]]})
            else:
                new_nodes.append(node)
        result["nodes"] = new_nodes

    edges = data.get("edges")
    if isinstance(edges, list):
        new_edges: list[Any] = []
        for edge in edges:
            if (
                isinstance(edge, dict)
                and isinstance(edge.get("type"), str)
                and edge["type"] in EDGE_TYPE_ALIASES
            ):
                new_edges.append({**edge, "type": EDGE_TYPE_ALIASES[edge["type"]]})
            else:
                new_edges.append(edge)
        result["edges"] = new_edges

    return result


# ---------------------------------------------------------------------------
# Tier 2 — auto-fix defaults / coercion
# ---------------------------------------------------------------------------


def auto_fix_graph(data: dict[str, Any]) -> tuple[dict[str, Any], list[GraphIssue]]:
    """Fill missing fields with defaults, coerce types, clamp ranges."""
    issues: list[GraphIssue] = []
    result = dict(data)

    nodes = data.get("nodes")
    if isinstance(nodes, list):
        new_nodes: list[Any] = []
        for i, node in enumerate(nodes):
            if not isinstance(node, dict):
                new_nodes.append(node)
                continue
            n = dict(node)
            name = n.get("name") or n.get("id") or f"index {i}"

            if not n.get("type") or not isinstance(n.get("type"), str):
                n["type"] = "file"
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'nodes[{i}] ("{name}"): missing "type" — defaulted to "file"',
                    "path": f"nodes[{i}].type",
                })

            complexity = n.get("complexity")
            if not complexity or complexity == "":
                n["complexity"] = "moderate"
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'nodes[{i}] ("{name}"): missing "complexity" — defaulted to "moderate"',
                    "path": f"nodes[{i}].complexity",
                })
            elif isinstance(complexity, str) and complexity in COMPLEXITY_ALIASES:
                original = complexity
                n["complexity"] = COMPLEXITY_ALIASES[complexity]
                issues.append({
                    "level": "auto-corrected",
                    "category": "alias",
                    "message": f'nodes[{i}] ("{name}"): complexity "{original}" — mapped to "{n["complexity"]}"',
                    "path": f"nodes[{i}].complexity",
                })

            if not isinstance(n.get("tags"), list):
                n["tags"] = []
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'nodes[{i}] ("{name}"): missing "tags" — defaulted to []',
                    "path": f"nodes[{i}].tags",
                })

            if not n.get("summary") or not isinstance(n.get("summary"), str):
                n["summary"] = n.get("name") or "No summary"
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'nodes[{i}] ("{name}"): missing "summary" — defaulted to name',
                    "path": f"nodes[{i}].summary",
                })

            new_nodes.append(n)
        result["nodes"] = new_nodes

    edges = data.get("edges")
    if isinstance(edges, list):
        new_edges: list[Any] = []
        for i, edge in enumerate(edges):
            if not isinstance(edge, dict):
                new_edges.append(edge)
                continue
            e = dict(edge)

            if not e.get("type") or not isinstance(e.get("type"), str):
                e["type"] = "depends_on"
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'edges[{i}]: missing "type" — defaulted to "depends_on"',
                    "path": f"edges[{i}].type",
                })

            direction = e.get("direction")
            if not direction or not isinstance(direction, str):
                e["direction"] = "forward"
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'edges[{i}]: missing "direction" — defaulted to "forward"',
                    "path": f"edges[{i}].direction",
                })
            elif direction in DIRECTION_ALIASES:
                original = direction
                e["direction"] = DIRECTION_ALIASES[direction]
                issues.append({
                    "level": "auto-corrected",
                    "category": "alias",
                    "message": f'edges[{i}]: direction "{original}" — mapped to "{e["direction"]}"',
                    "path": f"edges[{i}].direction",
                })

            weight = e.get("weight")
            if weight is None:
                e["weight"] = 0.5
                issues.append({
                    "level": "auto-corrected",
                    "category": "missing-field",
                    "message": f'edges[{i}]: missing "weight" — defaulted to 0.5',
                    "path": f"edges[{i}].weight",
                })
            elif isinstance(weight, str):
                original = weight
                parsed = _parse_float(weight)
                if parsed is not None:
                    e["weight"] = parsed
                    issues.append({
                        "level": "auto-corrected",
                        "category": "type-coercion",
                        "message": f'edges[{i}]: weight was string "{original}" — coerced to number',
                        "path": f"edges[{i}].weight",
                    })
                else:
                    e["weight"] = 0.5
                    issues.append({
                        "level": "auto-corrected",
                        "category": "type-coercion",
                        "message": f'edges[{i}]: weight "{original}" is not a valid number — defaulted to 0.5',
                        "path": f"edges[{i}].weight",
                    })

            w = e.get("weight")
            if isinstance(w, (int, float)) and not isinstance(w, bool) and (w < 0 or w > 1):
                original = w
                clamped = max(0.0, min(1.0, float(w)))
                e["weight"] = clamped
                issues.append({
                    "level": "auto-corrected",
                    "category": "out-of-range",
                    "message": f"edges[{i}]: weight {original} clamped to {clamped}",
                    "path": f"edges[{i}].weight",
                })

            new_edges.append(e)
        result["edges"] = new_edges

    return result, issues


def _parse_float(value: str) -> float | None:
    """JS parseFloat-style parse: leading numeric prefix, else None."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


# ---------------------------------------------------------------------------
# Tier 3/4 — full validation pipeline
# ---------------------------------------------------------------------------


def _build_invalid_collection_issue(name: str) -> GraphIssue:
    return {
        "level": "fatal",
        "category": "invalid-collection",
        "message": f'"{name}" must be an array when present',
        "path": name,
    }


def _build_errors(issues: list[GraphIssue], fatal: str | None = None) -> list[str] | None:
    messages = [issue["message"] for issue in issues]
    if fatal and fatal not in messages:
        messages.insert(0, fatal)
    return messages if messages else None


def validate_graph(data: Any) -> ValidationResult:
    """Repair-and-validate a knowledge graph (port of ``validateGraph``)."""
    # Tier 4: Fatal — not even an object
    if not isinstance(data, dict):
        fatal = "Invalid input: not an object"
        return {"success": False, "issues": [], "fatal": fatal, "errors": _build_errors([], fatal)}

    # Tier 1: Sanitize
    sanitized = sanitize_graph(data)

    # Normalize type aliases
    normalized = normalize_graph(sanitized)
    assert isinstance(normalized, dict)

    # Tier 2: Auto-fix
    fixed, issues = auto_fix_graph(normalized)

    # Tier 4: Fatal — malformed top-level collections
    for collection in ("nodes", "edges", "layers"):
        if collection in fixed and fixed[collection] is not None and not isinstance(
            fixed[collection], list
        ):
            issue = _build_invalid_collection_issue(collection)
            issues.append(issue)
            return {
                "success": False,
                "errors": _build_errors(issues, issue["message"]),
                "issues": issues,
                "fatal": issue["message"],
            }

    # Tier 4: Fatal — missing project metadata
    try:
        project = _ProjectMetaModel.model_validate(fixed.get("project"))
    except ValidationError:
        return {
            "success": False,
            "errors": _build_errors(issues, "Missing or invalid project metadata"),
            "issues": issues,
            "fatal": "Missing or invalid project metadata",
        }

    # Tier 3: validate nodes, drop broken
    valid_nodes: list[dict[str, Any]] = []
    fixed_nodes = fixed.get("nodes")
    if isinstance(fixed_nodes, list):
        for i, node in enumerate(fixed_nodes):
            try:
                model = _GraphNodeModel.model_validate(node)
                valid_nodes.append(model.model_dump(exclude_none=True))
            except ValidationError as exc:
                name = (node.get("name") or node.get("id")) if isinstance(node, dict) else None
                name = name or f"index {i}"
                issues.append({
                    "level": "dropped",
                    "category": "invalid-node",
                    "message": f'nodes[{i}] ("{name}"): {_first_error_message(exc)} — removed',
                    "path": f"nodes[{i}]",
                })

    # Tier 4: Fatal — no valid nodes
    if not valid_nodes:
        return {
            "success": False,
            "errors": _build_errors(issues, "No valid nodes found in knowledge graph"),
            "issues": issues,
            "fatal": "No valid nodes found in knowledge graph",
        }

    node_ids = {n["id"] for n in valid_nodes}

    # Tier 3: validate edges + referential integrity
    valid_edges: list[dict[str, Any]] = []
    fixed_edges = fixed.get("edges")
    if isinstance(fixed_edges, list):
        for i, edge in enumerate(fixed_edges):
            try:
                model = _GraphEdgeModel.model_validate(edge)
            except ValidationError as exc:
                issues.append({
                    "level": "dropped",
                    "category": "invalid-edge",
                    "message": f"edges[{i}]: {_first_error_message(exc)} — removed",
                    "path": f"edges[{i}]",
                })
                continue
            if model.source not in node_ids:
                issues.append({
                    "level": "dropped",
                    "category": "invalid-reference",
                    "message": f'edges[{i}]: source "{model.source}" does not exist in nodes — removed',
                    "path": f"edges[{i}].source",
                })
                continue
            if model.target not in node_ids:
                issues.append({
                    "level": "dropped",
                    "category": "invalid-reference",
                    "message": f'edges[{i}]: target "{model.target}" does not exist in nodes — removed',
                    "path": f"edges[{i}].target",
                })
                continue
            valid_edges.append(model.model_dump(exclude_none=True))

    # Validate layers (drop broken, filter dangling nodeIds)
    valid_layers: list[dict[str, Any]] = []
    fixed_layers = fixed.get("layers")
    if isinstance(fixed_layers, list):
        for i, layer in enumerate(fixed_layers):
            try:
                model = _LayerModel.model_validate(layer)
            except ValidationError as exc:
                issues.append({
                    "level": "dropped",
                    "category": "invalid-layer",
                    "message": f"layers[{i}]: {_first_error_message(exc)} — removed",
                    "path": f"layers[{i}]",
                })
                continue
            data_layer = model.model_dump()
            data_layer["nodeIds"] = [nid for nid in data_layer["nodeIds"] if nid in node_ids]
            valid_layers.append(data_layer)

    version = fixed.get("version")
    graph = {
        "version": version if isinstance(version, str) else "1.0.0",
        "project": project.model_dump(),
        "nodes": valid_nodes,
        "edges": valid_edges,
        "layers": valid_layers,
    }

    return {"success": True, "data": graph, "issues": issues, "errors": _build_errors(issues)}


__all__ = [
    "GraphIssue",
    "ValidationResult",
    "NODE_TYPE_ALIASES",
    "EDGE_TYPE_ALIASES",
    "COMPLEXITY_ALIASES",
    "DIRECTION_ALIASES",
    "sanitize_graph",
    "normalize_graph",
    "auto_fix_graph",
    "validate_graph",
]
