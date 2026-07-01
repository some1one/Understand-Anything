"""On-disk persistence — port of ``packages/core/src/persistence/index.ts``.

Reads/writes the ``.understand-anything/`` artifacts (graph, meta, fingerprints,
config, domain graph) as pretty-printed JSON. Absolute file paths in graph nodes
are sanitised to project-relative (or bare basename) before writing, so a
developer's directory layout never lands in ``knowledge-graph.json``.

Graphs are handled as plain dicts (the wire shape) so round-tripping preserves
exactly what was written; validation on load uses :func:`understand_core.schema.validate_graph`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .fingerprint import FingerprintStore
from .schema import validate_graph

_UA_DIR = ".understand-anything"
_GRAPH_FILE = "knowledge-graph.json"
_META_FILE = "meta.json"
_FINGERPRINT_FILE = "fingerprints.json"
_CONFIG_FILE = "config.json"
_DOMAIN_GRAPH_FILE = "domain-graph.json"

_DEFAULT_CONFIG: dict[str, Any] = {"autoUpdate": False}


def _ensure_dir(project_root: str | Path) -> Path:
    directory = Path(project_root) / _UA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _as_dict(graph: Any) -> dict[str, Any]:
    """Coerce a graph (pydantic model or dict) to a camelCase wire dict."""
    if isinstance(graph, dict):
        return graph
    if hasattr(graph, "model_dump"):
        return graph.model_dump(by_alias=True)
    return dict(graph)


def _sanitise_file_paths(graph: dict[str, Any], project_root: str | Path) -> dict[str, Any]:
    """Make absolute node ``filePath`` values project-relative (or basename).

    Three cases (mirroring ``sanitiseFilePaths``):
      1. inside project root  → relative path
      2. absolute but outside → bare filename
      3. already relative     → unchanged
    """
    root = str(project_root)
    normal_root = root if root.endswith("/") else root + "/"

    sanitised_nodes: list[Any] = []
    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(node.get("filePath"), str):
            sanitised_nodes.append(node)
            continue
        fp = node["filePath"]
        if not os.path.isabs(fp):
            sanitised_nodes.append(node)
            continue
        if fp.startswith(normal_root) or fp.startswith(root):
            sanitised_nodes.append({**node, "filePath": os.path.relpath(fp, root)})
        else:
            sanitised_nodes.append({**node, "filePath": os.path.basename(fp)})

    return {**graph, "nodes": sanitised_nodes}


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


def save_graph(project_root: str | Path, graph: Any) -> None:
    directory = _ensure_dir(project_root)
    sanitised = _sanitise_file_paths(_as_dict(graph), project_root)
    _write_json(directory / _GRAPH_FILE, sanitised)


def load_graph(
    project_root: str | Path, validate: bool = True
) -> dict[str, Any] | None:
    file_path = Path(project_root) / _UA_DIR / _GRAPH_FILE
    if not file_path.exists():
        return None

    data = json.loads(file_path.read_text(encoding="utf-8"))

    if validate:
        result = validate_graph(data)
        if not result.get("success"):
            raise ValueError(
                f"Invalid knowledge graph: {result.get('fatal') or 'unknown error'}"
            )
        return result.get("data")

    return data


# ---------------------------------------------------------------------------
# Analysis meta
# ---------------------------------------------------------------------------


def save_meta(project_root: str | Path, meta: Any) -> None:
    directory = _ensure_dir(project_root)
    payload = meta if isinstance(meta, dict) else meta.model_dump(by_alias=True, exclude_none=True)
    _write_json(directory / _META_FILE, payload)


def load_meta(project_root: str | Path) -> dict[str, Any] | None:
    file_path = Path(project_root) / _UA_DIR / _META_FILE
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def save_fingerprints(project_root: str | Path, store: FingerprintStore) -> None:
    directory = _ensure_dir(project_root)
    _write_json(directory / _FINGERPRINT_FILE, store)


def load_fingerprints(project_root: str | Path) -> FingerprintStore | None:
    file_path = Path(project_root) / _UA_DIR / _FINGERPRINT_FILE
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


def save_config(project_root: str | Path, config: Any) -> None:
    directory = _ensure_dir(project_root)
    payload = config if isinstance(config, dict) else config.model_dump(by_alias=True)
    _write_json(directory / _CONFIG_FILE, payload)


def load_config(project_root: str | Path) -> dict[str, Any]:
    file_path = Path(project_root) / _UA_DIR / _CONFIG_FILE
    if not file_path.exists():
        return dict(_DEFAULT_CONFIG)
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Domain graph
# ---------------------------------------------------------------------------


def save_domain_graph(project_root: str | Path, graph: Any) -> None:
    directory = _ensure_dir(project_root)
    sanitised = _sanitise_file_paths(_as_dict(graph), project_root)
    _write_json(directory / _DOMAIN_GRAPH_FILE, sanitised)


def load_domain_graph(
    project_root: str | Path, validate: bool = True
) -> dict[str, Any] | None:
    file_path = Path(project_root) / _UA_DIR / _DOMAIN_GRAPH_FILE
    if not file_path.exists():
        return None

    data = json.loads(file_path.read_text(encoding="utf-8"))

    if validate:
        result = validate_graph(data)
        if not result.get("success"):
            raise ValueError(
                f"Invalid domain graph: {result.get('fatal') or 'unknown error'}"
            )
        return result.get("data")

    return data


__all__ = [
    "save_graph",
    "load_graph",
    "save_meta",
    "load_meta",
    "save_fingerprints",
    "load_fingerprints",
    "save_config",
    "load_config",
    "save_domain_graph",
    "load_domain_graph",
]
