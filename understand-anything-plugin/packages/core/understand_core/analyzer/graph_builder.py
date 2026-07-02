"""Incremental knowledge-graph construction — port of ``analyzer/graph-builder.ts``.

``GraphBuilder`` accumulates file/function/class/non-code nodes plus their
edges and assembles a :class:`~understand_core.types.KnowledgeGraph`. New port
(no ``arch_analysis`` equivalent — the merge pipeline assembles graphs from
LLM-emitted batch JSON, whereas this builder is the in-process construction API).

Nodes and edges are built with ``model_construct`` so that intermediate graphs
(e.g. function nodes with empty summaries) are representable without tripping
the strict field validators on the canonical models — validation is the job of
:func:`understand_core.schema.validate_graph`, run downstream.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from arch_analysis.languages import detect_language

from ..types import (
    GraphEdge,
    GraphNode,
    GraphProject,
    KnowledgeGraph,
    StructuralAnalysis,
)

if TYPE_CHECKING:  # pragma: no cover — languages cluster ported separately
    from ..languages.language_registry import LanguageRegistry

logger = logging.getLogger(__name__)

# Maps a non-code "definition kind" to the graph node type it becomes.
_KIND_TO_NODE_TYPE: dict[str, str] = {
    "table": "table",
    "view": "table",
    "index": "table",
    "message": "schema",
    "type": "schema",
    "enum": "schema",
    "resource": "resource",
    "module": "resource",
    "service": "service",
    "deployment": "service",
    "job": "pipeline",
    "stage": "pipeline",
    "target": "pipeline",
    "route": "endpoint",
    "query": "endpoint",
    "mutation": "endpoint",
    "variable": "config",
    "output": "config",
}


def _as_dict(meta: Any) -> dict[str, Any]:
    """Coerce a pydantic model or mapping to a plain dict for attribute access."""
    if isinstance(meta, dict):
        return meta
    if hasattr(meta, "model_dump"):
        return meta.model_dump()
    return dict(meta)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-or-key getter for items that may be models or dicts."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class GraphBuilder:
    """Accumulates nodes/edges and assembles a knowledge graph."""

    def __init__(
        self,
        project_name: str,
        git_hash: str,
        language_registry: "LanguageRegistry | None" = None,
    ) -> None:
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self._languages: set[str] = set()
        self._node_ids: set[str] = set()
        self._edge_keys: set[str] = set()
        self._project_name = project_name
        self._git_hash = git_hash
        self._language_registry = language_registry

    def _detect_language(self, file_path: str) -> str:
        if self._language_registry is not None:
            config = self._language_registry.get_for_file(file_path)
            return _get(config, "id", "unknown") if config else "unknown"
        return detect_language(file_path)

    @staticmethod
    def _basename(file_path: str) -> str:
        parts = file_path.split("/")
        return parts[-1] if parts and parts[-1] else file_path

    def _register_language(self, file_path: str) -> None:
        lang = self._detect_language(file_path)
        if lang != "unknown":
            self._languages.add(lang)

    def add_file(self, file_path: str, meta: Any) -> None:
        """Add a plain file node from a ``FileMeta``-shaped object/dict."""
        self._register_language(file_path)
        name = self._basename(file_path)
        node_id = f"file:{file_path}"
        self._node_ids.add(node_id)
        self._nodes.append(
            {
                "id": node_id,
                "type": "file",
                "name": name,
                "filePath": file_path,
                "summary": _get(meta, "summary", ""),
                "tags": _get(meta, "tags", []) or [],
                "complexity": _get(meta, "complexity", "moderate"),
            }
        )

    def add_file_with_analysis(
        self,
        file_path: str,
        analysis: StructuralAnalysis | dict[str, Any],
        meta: Any,
    ) -> None:
        """Add a file node plus its function/class children with contains edges."""
        self._register_language(file_path)
        meta_d = _as_dict(meta)
        complexity = meta_d.get("complexity", "moderate")
        summaries: dict[str, str] = meta_d.get("summaries") or {}
        tags = meta_d.get("tags") or []

        file_name = self._basename(file_path)
        file_id = f"file:{file_path}"

        self._node_ids.add(file_id)
        self._nodes.append(
            {
                "id": file_id,
                "type": "file",
                "name": file_name,
                "filePath": file_path,
                "summary": meta_d.get("fileSummary", ""),
                "tags": tags,
                "complexity": complexity,
            }
        )

        functions = _get(analysis, "functions", []) or []
        classes = _get(analysis, "classes", []) or []

        for fn in functions:
            fn_name = _get(fn, "name")
            func_id = f"function:{file_path}:{fn_name}"
            self._node_ids.add(func_id)
            self._nodes.append(
                {
                    "id": func_id,
                    "type": "function",
                    "name": fn_name,
                    "filePath": file_path,
                    "lineRange": _get(fn, "lineRange"),
                    "summary": summaries.get(fn_name, ""),
                    "tags": [],
                    "complexity": complexity,
                }
            )
            self._edges.append(
                {
                    "source": file_id,
                    "target": func_id,
                    "type": "contains",
                    "direction": "forward",
                    "weight": 1,
                }
            )

        for cls in classes:
            cls_name = _get(cls, "name")
            class_id = f"class:{file_path}:{cls_name}"
            self._node_ids.add(class_id)
            self._nodes.append(
                {
                    "id": class_id,
                    "type": "class",
                    "name": cls_name,
                    "filePath": file_path,
                    "lineRange": _get(cls, "lineRange"),
                    "summary": summaries.get(cls_name, ""),
                    "tags": [],
                    "complexity": complexity,
                }
            )
            self._edges.append(
                {
                    "source": file_id,
                    "target": class_id,
                    "type": "contains",
                    "direction": "forward",
                    "weight": 1,
                }
            )

    def add_import_edge(self, from_file: str, to_file: str) -> None:
        key = f"imports|file:{from_file}|file:{to_file}"
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._edges.append(
            {
                "source": f"file:{from_file}",
                "target": f"file:{to_file}",
                "type": "imports",
                "direction": "forward",
                "weight": 0.7,
            }
        )

    def add_call_edge(
        self,
        caller_file: str,
        caller_func: str,
        callee_file: str,
        callee_func: str,
    ) -> None:
        key = (
            f"calls|function:{caller_file}:{caller_func}"
            f"|function:{callee_file}:{callee_func}"
        )
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._edges.append(
            {
                "source": f"function:{caller_file}:{caller_func}",
                "target": f"function:{callee_file}:{callee_func}",
                "type": "calls",
                "direction": "forward",
                "weight": 0.8,
            }
        )

    def add_non_code_file(self, file_path: str, meta: Any) -> str:
        """Add a non-code file node; returns its node ID."""
        self._register_language(file_path)
        name = self._basename(file_path)
        node_type = _get(meta, "nodeType") or "file"
        node_id = f"{node_type}:{file_path}"
        self._node_ids.add(node_id)
        self._nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "name": name,
                "filePath": file_path,
                "summary": _get(meta, "summary", ""),
                "tags": _get(meta, "tags", []) or [],
                "complexity": _get(meta, "complexity", "moderate"),
            }
        )
        return node_id

    def add_non_code_file_with_analysis(self, file_path: str, meta: Any) -> None:
        """Add a non-code file node plus its definition/service/etc. children."""
        file_id = self.add_non_code_file(file_path, meta)
        complexity = _get(meta, "complexity", "moderate")

        for definition in _get(meta, "definitions", []) or []:
            kind = _get(definition, "kind")
            name = _get(definition, "name")
            fields = _get(definition, "fields", []) or []
            self._add_child_node(
                {
                    "id": f"{kind}:{file_path}:{name}",
                    "type": self._map_kind_to_node_type(kind),
                    "name": name,
                    "filePath": file_path,
                    "lineRange": _get(definition, "lineRange"),
                    "summary": f"{kind}: {name} ({len(fields)} fields)",
                    "tags": [],
                    "complexity": complexity,
                },
                file_id,
            )

        for svc in _get(meta, "services", []) or []:
            name = _get(svc, "name")
            image = _get(svc, "image")
            summary = f"Service {name}" + (f" (image: {image})" if image else "")
            self._add_child_node(
                {
                    "id": f"service:{file_path}:{name}",
                    "type": "service",
                    "name": name,
                    "filePath": file_path,
                    "summary": summary,
                    "tags": [],
                    "complexity": complexity,
                },
                file_id,
            )

        for ep in _get(meta, "endpoints", []) or []:
            method = _get(ep, "method") or ""
            path = _get(ep, "path")
            name = f"{method} {path}".strip()
            self._add_child_node(
                {
                    "id": f"endpoint:{file_path}:{path}",
                    "type": "endpoint",
                    "name": name,
                    "filePath": file_path,
                    "lineRange": _get(ep, "lineRange"),
                    "summary": f"Endpoint: {name}",
                    "tags": [],
                    "complexity": complexity,
                },
                file_id,
            )

        for step in _get(meta, "steps", []) or []:
            name = _get(step, "name")
            self._add_child_node(
                {
                    "id": f"step:{file_path}:{name}",
                    "type": "pipeline",
                    "name": name,
                    "filePath": file_path,
                    "lineRange": _get(step, "lineRange"),
                    "summary": f"Step: {name}",
                    "tags": [],
                    "complexity": complexity,
                },
                file_id,
            )

        for res in _get(meta, "resources", []) or []:
            name = _get(res, "name")
            kind = _get(res, "kind")
            self._add_child_node(
                {
                    "id": f"resource:{file_path}:{name}",
                    "type": "resource",
                    "name": name,
                    "filePath": file_path,
                    "lineRange": _get(res, "lineRange"),
                    "summary": f"Resource: {name} ({kind})",
                    "tags": [],
                    "complexity": complexity,
                },
                file_id,
            )

    def _add_child_node(self, node: dict[str, Any], parent_id: str) -> None:
        if node["id"] in self._node_ids:
            logger.warning(
                '[GraphBuilder] Duplicate node ID "%s" — skipping', node["id"]
            )
            return
        self._node_ids.add(node["id"])
        self._nodes.append(node)
        self._edges.append(
            {
                "source": parent_id,
                "target": node["id"],
                "type": "contains",
                "direction": "forward",
                "weight": 1,
            }
        )

    def _map_kind_to_node_type(self, kind: str) -> str:
        mapped = _KIND_TO_NODE_TYPE.get(kind)
        if not mapped:
            logger.warning(
                '[GraphBuilder] Unknown definition kind "%s" — falling back to '
                '"concept" node type',
                kind,
            )
            return "concept"
        return mapped

    def build(self) -> KnowledgeGraph:
        """Assemble and return the accumulated graph."""
        project = GraphProject.model_construct(
            name=self._project_name,
            languages=sorted(self._languages),
            frameworks=[],
            description="",
            analyzedAt=datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            gitCommitHash=self._git_hash,
        )
        nodes = [GraphNode.model_construct(**n) for n in self._nodes]
        edges = [GraphEdge.model_construct(**e) for e in self._edges]
        return KnowledgeGraph.model_construct(
            version="1.0.0",
            project=project,
            nodes=nodes,
            edges=edges,
            layers=[],
        )
