#!/usr/bin/env python3
"""Load part graph(s) — or the full merged graph — as compact prompt context.

Uses the selected project data directory (``.ua`` or legacy):
  * ``--all``            → the merged ``knowledge-graph.json``
  * ``<part>[,<part>]``  → those parts' ``partitions/<part>.knowledge-graph.json``
  * (nothing)           → the parts in ``config.includedParts``

Selected parts are lightly merged (nodes deduped by id, edges by
(source,target,type)) and rendered as a compact listing so the caller gets a
smaller graph than the whole repo when the whole isn't needed.

Usage:
    python load_graph.py <project-root> [--all | <part>[,<part>...]]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SUFFIX = ".knowledge-graph.json"


sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from data_directory import data_dir

def _part_to_filename(part: str) -> str:
    return part.replace("/", "~") + _SUFFIX


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data.get("nodes"), list) and isinstance(data.get("edges"), list):
        return data
    return None


def _merge(graphs: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict] = {}
    for g in graphs:
        for n in g.get("nodes", []):
            nid = n.get("id")
            if not nid:
                continue
            # A real node beats a boundary stub.
            existing = nodes.get(nid)
            if existing is None or (existing.get("stub") and not n.get("stub")):
                nodes[nid] = n
    edges: dict[tuple, dict] = {}
    for g in graphs:
        for e in g.get("edges", []):
            edges[(e.get("source"), e.get("target"), e.get("type"))] = e
    node_ids = set(nodes)
    valid_edges = [
        e for e in edges.values() if e.get("source") in node_ids and e.get("target") in node_ids
    ]
    project = graphs[0].get("project", {}) if graphs else {}
    layers: dict[str, dict] = {}
    for g in graphs:
        for layer in g.get("layers", []):
            lid = layer.get("id")
            if not lid:
                continue
            if lid in layers:
                merged_ids = set(layers[lid].get("nodeIds", [])) | set(layer.get("nodeIds", []))
                layers[lid]["nodeIds"] = sorted(nid for nid in merged_ids if nid in node_ids)
            else:
                layers[lid] = {**layer, "nodeIds": [nid for nid in layer.get("nodeIds", []) if nid in node_ids]}
    return {
        "project": project,
        "nodes": list(nodes.values()),
        "edges": valid_edges,
        "layers": list(layers.values()),
    }


def _truncate(text: str, limit: int = 140) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render(graph: dict[str, Any], scope_label: str) -> str:
    project = graph.get("project", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    layers = graph.get("layers", [])
    out: list[str] = []
    out.append(f"# Knowledge graph — {scope_label}")
    out.append(
        f"Project: {project.get('name', '?')} — {_truncate(project.get('description', ''), 200)}"
    )
    langs = ", ".join(project.get("languages", []))
    if langs:
        out.append(f"Languages: {langs}")
    out.append(f"\n{len(nodes)} nodes, {len(edges)} edges, {len(layers)} layers\n")

    if layers:
        out.append("## Layers")
        for layer in layers:
            out.append(f"- {layer.get('name', layer.get('id'))}: {len(layer.get('nodeIds', []))} nodes")
        out.append("")

    out.append("## Nodes")
    for n in sorted(nodes, key=lambda x: (x.get("type", ""), x.get("id", ""))):
        stub = " (external)" if n.get("stub") else ""
        out.append(
            f"- `{n.get('id')}` [{n.get('type')}]{stub} {n.get('name', '')} — {_truncate(n.get('summary', ''))}"
        )

    out.append("\n## Edges")
    for e in edges:
        out.append(f"- {e.get('source')} --{e.get('type')}--> {e.get('target')}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write("Usage: load_graph.py <project-root> [--all | <part>[,<part>...]]\n")
        return 1

    project_root = Path(args[0]).resolve()
    ua = data_dir(project_root)
    selector = args[1] if len(args) > 1 else ""

    if selector == "--all":
        graph = _load(ua / "knowledge-graph.json")
        if graph is None:
            sys.stderr.write("No knowledge-graph.json found. Run /understand first.\n")
            return 1
        print(_render(graph, "full (all parts)"))
        return 0

    if selector:
        parts = [p.strip() for p in selector.split(",") if p.strip()]
    else:
        try:
            config = json.loads((ua / "config.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
        parts = config.get("includedParts") or []

    if not parts:
        sys.stderr.write(
            "No parts specified and no includedParts in config. "
            "Use --all or name parts.\n"
        )
        return 1

    graphs: list[dict[str, Any]] = []
    missing: list[str] = []
    for part in parts:
        g = _load(ua / "partitions" / _part_to_filename(part))
        if g is None:
            missing.append(part)
        else:
            graphs.append(g)
    if not graphs:
        sys.stderr.write(f"No partition graphs found for: {', '.join(parts)}\n")
        return 1
    if missing:
        sys.stderr.write(f"Warning: no graph for parts: {', '.join(missing)}\n")

    print(_render(_merge(graphs), f"parts: {', '.join(parts)}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
