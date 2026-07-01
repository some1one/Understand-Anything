#!/usr/bin/env python3
"""Normalize architecture-analyzer layers deterministically."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

FILE_PREFIXES = {
    "file", "config", "document", "service", "pipeline",
    "table", "schema", "resource", "endpoint",
}


def kebab(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return out or "unnamed"


def node_path(node: dict[str, Any]) -> str | None:
    fp = node.get("filePath")
    if isinstance(fp, str) and fp:
        return fp
    nid = node.get("id")
    if isinstance(nid, str) and ":" in nid:
        return nid.split(":", 2)[1]
    return None


def normalize_node_id(value: Any, by_path: dict[str, str]) -> str | None:
    if isinstance(value, dict):
        value = value.get("id") or value.get("filePath") or value.get("path")
    if not isinstance(value, str) or not value:
        return None
    if ":" in value and value.split(":", 1)[0] in FILE_PREFIXES | {"function", "class", "module", "concept"}:
        return value
    return by_path.get(value) or f"file:{value}"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("Usage: normalize_layers.py <project-root>\n")
        return 1

    project_root = Path(args[0]).resolve()
    inter = project_root / ".understand-anything" / "intermediate"
    graph = json.loads((inter / "assembled-graph.json").read_text(encoding="utf-8"))
    raw = json.loads((inter / "layers.json").read_text(encoding="utf-8"))
    layers = raw.get("layers", raw) if isinstance(raw, dict) else raw
    if not isinstance(layers, list):
        layers = []

    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict)]
    node_ids = {n.get("id") for n in nodes if isinstance(n.get("id"), str)}
    by_path = {
        p: n["id"]
        for n in nodes
        if isinstance(n.get("id"), str)
        for p in [node_path(n)]
        if p
    }

    normalized: list[dict[str, Any]] = []
    seen_layer_ids: set[str] = set()
    assigned_nodes: set[str] = set()
    for index, layer in enumerate(layers, start=1):
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("name") or layer.get("id") or f"Layer {index}")
        layer_id = str(layer.get("id") or f"layer:{kebab(name)}")
        if not layer_id.startswith("layer:"):
            layer_id = f"layer:{kebab(layer_id)}"
        else:
            layer_id = f"layer:{kebab(layer_id.removeprefix('layer:'))}"
        base_id = layer_id
        suffix = 2
        while layer_id in seen_layer_ids:
            layer_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_layer_ids.add(layer_id)

        raw_ids = layer.get("nodeIds", layer.get("nodes", []))
        node_ids_out: list[str] = []
        if isinstance(raw_ids, list):
            for raw_id in raw_ids:
                nid = normalize_node_id(raw_id, by_path)
                if nid in node_ids and nid not in assigned_nodes:
                    node_ids_out.append(nid)
                    assigned_nodes.add(nid)
        if not node_ids_out:
            continue
        normalized.append(
            {
                "id": layer_id,
                "name": name,
                "description": str(layer.get("description") or f"Files in {name}."),
                "nodeIds": node_ids_out,
            }
        )

    out_path = inter / "layers.json"
    out_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps({"outputPath": str(out_path), "layers": len(normalized)}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
