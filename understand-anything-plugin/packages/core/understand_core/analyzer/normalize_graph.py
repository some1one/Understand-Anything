"""Batch-output normalization — port of ``analyzer/normalize-graph.ts``.

Overlaps :mod:`arch_analysis.merge_batch_graphs` conceptually (both fix node
IDs / complexity and clean edges), but the two have different algorithms and
contracts: the TS ``normalizeBatchOutput`` runs *before* the validate-graph
pipeline, returns an explicit :class:`NormalizeBatchResult` with an ``id_map``
and detailed :class:`NormalizationStats`/:class:`DroppedEdge` records, and uses
a prefix-peeling normalizer with step-node flow-slug reconstruction. The merge
script's ``normalize_node_id`` differs subtly (e.g. ``func:`` → ``function:``
canonicalization, ``__nofilepath__`` placeholders). To preserve the exact
behaviour the tests assert, this module is ported fresh rather than reusing the
merge script.
"""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_VALID_PREFIXES: frozenset[str] = frozenset(
    {
        "file", "func", "class", "module", "concept",
        "config", "document", "service", "table", "endpoint",
        "pipeline", "schema", "resource",
        "domain", "flow", "step",
    }
)

_TYPE_TO_PREFIX: dict[str, str] = {
    "file": "file",
    "function": "func",
    "class": "class",
    "module": "module",
    "concept": "concept",
    "config": "config",
    "document": "document",
    "service": "service",
    "table": "table",
    "endpoint": "endpoint",
    "pipeline": "pipeline",
    "schema": "schema",
    "resource": "resource",
    "domain": "domain",
    "flow": "flow",
    "step": "step",
}


def _strip_to_valid_prefix(node_id: str) -> tuple[str | None, str]:
    """Strip non-valid prefixes from an ID.

    Returns ``(prefix, path)`` where ``prefix`` is the first valid prefix found
    (or ``None``) and ``path`` is the remainder.
    """
    remaining = node_id

    while True:
        colon_idx = remaining.find(":")
        if colon_idx <= 0:
            break

        segment = remaining[:colon_idx]
        if segment in _VALID_PREFIXES:
            rest = remaining[colon_idx + 1 :]
            inner_colon_idx = rest.find(":")
            if inner_colon_idx > 0 and rest[:inner_colon_idx] in _VALID_PREFIXES:
                # Double-prefixed — skip the outer, recurse on inner
                remaining = rest
                continue
            return segment, rest

        # Not a valid prefix — strip it and continue
        remaining = remaining[colon_idx + 1 :]

    return None, remaining


def normalize_node_id(node_id: str, node: dict[str, Any]) -> str:
    """Normalize a node ID to the canonical ``type:path`` format.

    Handles double-prefixed IDs, project-name-prefixed IDs, and bare paths.
    Idempotent — correct IDs pass through unchanged. ``node`` carries
    ``type`` and optional ``filePath`` / ``name`` / ``parentFlowSlug``.
    """
    trimmed = node_id.strip()
    if not trimmed:
        return trimmed

    node_type = node.get("type", "")
    file_path = node.get("filePath")
    name = node.get("name")
    parent_flow_slug = node.get("parentFlowSlug")

    expected_prefix = _TYPE_TO_PREFIX.get(node_type)
    prefix, path = _strip_to_valid_prefix(trimmed)

    if prefix:
        # For step nodes with filePath, reconstruct as
        # step:flowSlug:filePath:stepSlug to avoid cross-flow collisions.
        if node_type == "step" and file_path:
            segments = path.split(":")
            step_slug = segments[-1] if segments else path
            flow_slug = segments[-2] if len(segments) > 1 else ""
            if flow_slug:
                return f"{prefix}:{flow_slug}:{file_path}:{step_slug}"
            return f"{prefix}:{file_path}:{step_slug}"
        return f"{prefix}:{path}"

    # No valid prefix found — bare path
    if expected_prefix:
        # For func/class, reconstruct from filePath + name if available
        if node_type in ("function", "class") and file_path and name:
            return f"{expected_prefix}:{file_path}:{name}"
        # For step nodes with filePath, reconstruct from slugified path
        if node_type == "step" and file_path:
            slug = re.sub(r"\s+", "-", path.lower())
            if parent_flow_slug:
                return f"{expected_prefix}:{parent_flow_slug}:{file_path}:{slug}"
            return f"{expected_prefix}:{file_path}:{slug}"
        return f"{expected_prefix}:{path}"

    return trimmed


_VALID_COMPLEXITIES: frozenset[str] = frozenset({"simple", "moderate", "complex"})

_COMPLEXITY_STRING_MAP: dict[str, str] = {
    "low": "simple",
    "easy": "simple",
    "trivial": "simple",
    "basic": "simple",
    "medium": "moderate",
    "intermediate": "moderate",
    "mid": "moderate",
    "average": "moderate",
    "high": "complex",
    "hard": "complex",
    "difficult": "complex",
    "advanced": "complex",
}


def normalize_complexity(value: Any) -> str:
    """Normalize a complexity value to ``simple`` / ``moderate`` / ``complex``.

    Handles string aliases and numeric scales; defaults to ``moderate``.
    """
    if isinstance(value, str):
        lower = value.lower().strip()
        if lower in _VALID_COMPLEXITIES:
            return lower
        aliased = _COMPLEXITY_STRING_MAP.get(lower)
        if aliased:
            return aliased
        return "moderate"

    # bool is an int subclass in Python; the TS source only treats real numbers.
    if isinstance(value, bool):
        return "moderate"

    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 1:
        if value <= 3:
            return "simple"
        if value <= 6:
            return "moderate"
        return "complex"

    return "moderate"


class DroppedEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    source: str
    target: str
    type: str
    reason: str  # "missing-source" | "missing-target" | "missing-both"


class NormalizationStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    idsFixed: int = 0
    complexityFixed: int = 0
    edgesRewritten: int = 0
    danglingEdgesDropped: int = 0
    droppedEdges: list[DroppedEdge] = Field(default_factory=list)


class NormalizeBatchResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow", arbitrary_types_allowed=True)

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    idMap: dict[str, str]
    stats: NormalizationStats


_PREFIX_TO_TYPE: dict[str, str] = {
    "file": "file", "func": "function", "class": "class", "module": "module",
    "concept": "concept", "config": "config", "document": "document",
    "service": "service", "table": "table", "endpoint": "endpoint",
    "pipeline": "pipeline", "schema": "schema", "resource": "resource",
    "domain": "domain", "flow": "flow", "step": "step",
}


def _infer_type_from_id(node_id: str) -> str:
    """Infer node type from an ID's prefix (``step:foo`` → ``step``); else file."""
    colon_idx = node_id.find(":")
    if colon_idx > 0:
        prefix = node_id[:colon_idx]
        if prefix in _PREFIX_TO_TYPE:
            return _PREFIX_TO_TYPE[prefix]
    return "file"


def normalize_batch_output(
    data: dict[str, list[dict[str, Any]]],
) -> NormalizeBatchResult:
    """Normalize a merged batch output.

    Fixes node IDs and numeric complexity, rewrites edge references,
    deduplicates nodes (keeping the last occurrence) and edges, and drops
    dangling edges. Runs before the validate-graph pipeline.
    """
    stats = NormalizationStats()
    id_map: dict[str, str] = {}

    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])

    # Build step→flow slug map from flow_step edges so bare-path step IDs can
    # include the flow discriminator to avoid collisions.
    step_to_flow_slug: dict[str, str] = {}
    flow_node_names: dict[str, str] = {}
    for raw in raw_nodes:
        if str(raw.get("type") or "") == "flow" and raw.get("id") and raw.get("name"):
            flow_node_names[str(raw["id"])] = re.sub(
                r"\s+", "-", str(raw["name"]).lower()
            )
    for raw in raw_edges:
        if (
            str(raw.get("type") or "") == "flow_step"
            and raw.get("source")
            and raw.get("target")
        ):
            flow_slug = flow_node_names.get(str(raw["source"]))
            if flow_slug:
                step_to_flow_slug[str(raw["target"])] = flow_slug

    # Pass 1: Normalize node IDs and numeric complexity
    nodes: list[dict[str, Any]] = []
    for raw in raw_nodes:
        old_id = str(raw.get("id") or "")
        node_type = str(raw.get("type") or "file")
        new_id = normalize_node_id(
            old_id,
            {
                "type": node_type,
                "filePath": raw["filePath"]
                if isinstance(raw.get("filePath"), str)
                else None,
                "name": raw["name"] if isinstance(raw.get("name"), str) else None,
                "parentFlowSlug": step_to_flow_slug.get(old_id)
                if node_type == "step"
                else None,
            },
        )

        if new_id != old_id:
            stats.idsFixed += 1
        id_map[old_id] = new_id

        result: dict[str, Any] = {**raw, "id": new_id}

        # Normalize both numeric and non-canonical string complexity values.
        if raw.get("complexity") is not None:
            normalized = normalize_complexity(raw["complexity"])
            if normalized != raw["complexity"]:
                result["complexity"] = normalized
                stats.complexityFixed += 1

        nodes.append(result)

    # Deduplicate nodes (keep last occurrence)
    seen_ids: dict[str, int] = {}
    for i, node in enumerate(nodes):
        seen_ids[str(node["id"])] = i
    deduped = [node for i, node in enumerate(nodes) if seen_ids[str(node["id"])] == i]
    valid_node_ids = {str(n["id"]) for n in deduped}

    # Pass 2: Rewrite edge references and deduplicate
    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for raw in raw_edges:
        old_source = str(raw.get("source") or "")
        old_target = str(raw.get("target") or "")
        new_source = id_map.get(old_source, old_source)
        new_target = id_map.get(old_target, old_target)

        # Fallback: if endpoint not found in id_map, normalize it directly.
        if new_source not in valid_node_ids:
            inferred_type = _infer_type_from_id(new_source)
            normalized = normalize_node_id(new_source, {"type": inferred_type})
            if normalized in valid_node_ids:
                new_source = normalized
        if new_target not in valid_node_ids:
            inferred_type = _infer_type_from_id(new_target)
            normalized = normalize_node_id(new_target, {"type": inferred_type})
            if normalized in valid_node_ids:
                new_target = normalized

        if new_source != old_source or new_target != old_target:
            stats.edgesRewritten += 1

        if new_source not in valid_node_ids or new_target not in valid_node_ids:
            missing_source = new_source not in valid_node_ids
            missing_target = new_target not in valid_node_ids
            stats.danglingEdgesDropped += 1
            if missing_source and missing_target:
                reason = "missing-both"
            elif missing_source:
                reason = "missing-source"
            else:
                reason = "missing-target"
            stats.droppedEdges.append(
                DroppedEdge(
                    source=new_source,
                    target=new_target,
                    type=str(raw.get("type") or ""),
                    reason=reason,
                )
            )
            continue

        # Deduplicate by composite key (source + target + type)
        edge_type = str(raw.get("type") or "")
        edge_key = f"{new_source}|{new_target}|{edge_type}"
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)

        edges.append({**raw, "source": new_source, "target": new_target})

    return NormalizeBatchResult(
        nodes=deduped,
        edges=edges,
        idMap=id_map,
        stats=stats,
    )
