"""Boundary stubs for cross-part edges in scoped (per-part) analysis.

When a part is analyzed in isolation, its deterministically-seeded edges can
point at nodes that live in *other* parts (e.g. an ``imports`` edge into a
sibling folder). Those target nodes don't exist in the part's own graph, so the
standard assembly/merge would drop the edge as dangling — silently losing every
cross-part relationship.

The fix is a lightweight **stub node** for each such far-side target: enough
fields to be a valid :class:`understand_core.models.GraphNode`, marked
``stub: True``. Each part graph is then self-valid, and at merge time the real
node (from the sibling part) wins over the stub — see
:func:`understand_core.merge_subdomain_graphs.merge_graphs`.

This module is pure (no IO); the pipeline calls :func:`add_boundary_stubs` after
assembling a part and before writing ``partitions/<part>.knowledge-graph.json``.
"""

from __future__ import annotations

from typing import Any

# Valid node types (mirrors models.NodeType). A stub whose parsed type is not
# one of these falls back to "file" (import targets are always file-level).
_VALID_TYPES = frozenset(
    {
        "file", "function", "class", "module", "concept",
        "config", "document", "service", "table", "endpoint",
        "pipeline", "schema", "resource",
        "domain", "flow", "step",
    }
)

_STUB_SUMMARY = "External reference — defined in another part, not analyzed here."


def parse_node_id(node_id: str) -> tuple[str, str, str] | None:
    """Split a node id into ``(type, filePath, name)``.

    Node ids are ``<type>:<path>`` or ``<type>:<path>:<name>`` (POSIX paths,
    which never contain ``:``). Returns ``None`` for ids without a type prefix.
    """
    if not isinstance(node_id, str) or ":" not in node_id:
        return None
    parts = node_id.split(":")
    node_type = parts[0]
    if len(parts) == 2:
        path = parts[1]
        name = path.rsplit("/", 1)[-1]
    else:
        path = ":".join(parts[1:-1])
        name = parts[-1]
    return node_type, path, name


def _make_stub(node_id: str, node_type: str, path: str, name: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type if node_type in _VALID_TYPES else "file",
        "name": name or node_id,
        "summary": _STUB_SUMMARY,
        "tags": [],
        "complexity": "simple",
        "filePath": path,
        "stub": True,
    }


def add_boundary_stubs(graph: dict[str, Any], known_paths: set[str]) -> dict[str, Any]:
    """Return ``graph`` with stub nodes added for cross-part edge endpoints.

    A stub is created for any edge ``source``/``target`` id that (a) is not
    already a node in ``graph`` and (b) references a ``filePath`` present in
    ``known_paths`` (the whole-repo file set) — i.e. a real file that lives in
    another part. Endpoints that don't resolve to a known file are left alone
    (they get dropped downstream as before).
    """
    nodes = graph.get("nodes", [])
    node_ids = {n.get("id") for n in nodes if isinstance(n, dict)}
    stubs: dict[str, dict[str, Any]] = {}

    for edge in graph.get("edges", []):
        if not isinstance(edge, dict):
            continue
        for endpoint in ("source", "target"):
            eid = edge.get(endpoint)
            if not eid or eid in node_ids or eid in stubs:
                continue
            parsed = parse_node_id(eid)
            if parsed is None:
                continue
            node_type, path, name = parsed
            if path and path in known_paths:
                stubs[eid] = _make_stub(eid, node_type, path, name)

    if not stubs:
        return graph
    return {**graph, "nodes": [*nodes, *stubs.values()]}
