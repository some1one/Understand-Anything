#!/usr/bin/env python3
"""Merge subdomain knowledge-graph files into one.

Python module port of ``skills/understand/merge-subdomain-graphs.py``. Tour
merging has been removed — new graphs no longer carry a ``tour`` key (a stray
legacy ``tour`` key on an input graph is simply ignored).

Auto-discovers ``*knowledge-graph*.json`` files in ``.understand-anything/``
(excluding ``knowledge-graph.json`` itself), loads the existing
``knowledge-graph.json`` as a base if present, and merges everything into a
single ``knowledge-graph.json``.

Usage:
    python -m understand_core.merge_subdomain_graphs <project-root> [file1.json ...]

If no files are specified, auto-discovers subdomain graphs. The main
``knowledge-graph.json`` is loaded as a base but never as a discovery input
(prevents self-merging on repeated runs).

Output:
    <project-root>/.understand-anything/knowledge-graph.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _num(v: Any) -> float:
    """Coerce a value to float for safe comparison (handles string weights)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_graph(path: Path) -> dict[str, Any] | None:
    """Load and minimally validate a knowledge graph JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  Skipping {path.name}: {e}", file=sys.stderr)
        return None

    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        print(f"  Skipping {path.name}: missing nodes or edges array", file=sys.stderr)
        return None

    return data


def discover_partition_graphs(ua_dir: Path) -> list[Path]:
    """Find all subdomain/part graph files under ``.understand-anything/``.

    Includes both the legacy root-level ``*knowledge-graph*.json`` (excluding the
    merged ``knowledge-graph.json`` itself) and per-part graphs written to
    ``partitions/<part>.knowledge-graph.json``.
    """
    root_level = [
        p
        for p in ua_dir.glob("*knowledge-graph*.json")
        if p.name != "knowledge-graph.json"
    ]
    partitions = list((ua_dir / "partitions").glob("*.knowledge-graph.json"))
    return sorted(set(root_level + partitions))


def _load_included_parts(project_root: Path) -> list[str] | None:
    """Return ``config.includedParts`` (a selection) or ``None`` if unset."""
    config_path = project_root / ".understand-anything" / "config.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    included = config.get("includedParts")
    if isinstance(included, list) and included:
        return [str(p) for p in included]
    return None


def _part_of(path: Path) -> str | None:
    """Read a partition graph's ``part`` field without a full parse cost."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    part = data.get("part")
    return str(part) if isinstance(part, str) else None


def select_partition_graphs(project_root: Path) -> list[Path]:
    """Discover partition/subdomain graphs, filtered to ``config.includedParts``.

    Graphs without a ``part`` field (legacy subdomain files) are always kept.
    """
    ua_dir = project_root / ".understand-anything"
    files = discover_partition_graphs(ua_dir)
    included = _load_included_parts(project_root)
    if included is not None:
        files = [f for f in files if _part_of(f) in (None, *included)]
    return files


def merge_graphs(graphs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Merge multiple knowledge graph dicts into one. Returns (merged, report_lines)."""

    node_dedup_by_type: Counter[str] = Counter()
    unfixable: list[str] = []

    total_input_nodes = sum(len(g.get("nodes", [])) for g in graphs)
    total_input_edges = sum(len(g.get("edges", [])) for g in graphs)

    # Nodes: deduplicate by id, later occurrence wins — EXCEPT a real node always
    # beats a boundary stub (``stub: True``), regardless of order, so cross-part
    # stubs are replaced by the real node from whichever part defines it.
    nodes_by_id: dict[str, dict] = {}
    for g in graphs:
        for node in g.get("nodes", []):
            nid = node.get("id")
            if not nid:
                unfixable.append(
                    f"Node with no 'id' (name={node.get('name', '?')}, type={node.get('type', '?')})"
                )
                continue
            existing = nodes_by_id.get(nid)
            if existing is None:
                nodes_by_id[nid] = node
                continue
            existing_stub = bool(existing.get("stub"))
            incoming_stub = bool(node.get("stub"))
            if existing_stub and not incoming_stub:
                nodes_by_id[nid] = node  # real replaces stub (not a true dedup)
            elif not existing_stub and incoming_stub:
                pass  # keep the real node, ignore the stub
            else:  # both real or both stub → later wins, count as a dedup
                node_dedup_by_type[node.get("type", "?")] += 1
                nodes_by_id[nid] = node

    # Edges: deduplicate by (source, target, type), higher weight wins.
    edge_dedup_count = 0
    edges_by_key: dict[tuple[str, str, str], dict] = {}
    for g in graphs:
        for edge in g.get("edges", []):
            key = (edge.get("source", ""), edge.get("target", ""), edge.get("type", ""))
            existing = edges_by_key.get(key)
            if existing is None:
                edges_by_key[key] = edge
            else:
                edge_dedup_count += 1
                if _num(edge.get("weight", 0)) > _num(existing.get("weight", 0)):
                    edges_by_key[key] = edge

    # Drop edges referencing missing nodes.
    node_ids = set(nodes_by_id.keys())
    valid_edges: list[dict] = []
    for e in edges_by_key.values():
        src, tgt = e.get("source", ""), e.get("target", "")
        if src in node_ids and tgt in node_ids:
            valid_edges.append(e)
        else:
            missing = []
            if src not in node_ids:
                missing.append(f"source '{src}'")
            if tgt not in node_ids:
                missing.append(f"target '{tgt}'")
            unfixable.append(
                f"Edge {src} → {tgt} ({e.get('type', '?')}): dropped, missing {', '.join(missing)}"
            )

    # Layers: merge by id, union nodeIds.
    layers_by_id: dict[str, dict] = {}
    for g in graphs:
        for layer in g.get("layers", []):
            lid = layer.get("id", "")
            if lid in layers_by_id:
                existing_ids = set(layers_by_id[lid].get("nodeIds", []))
                existing_ids.update(layer.get("nodeIds", []))
                layers_by_id[lid]["nodeIds"] = list(existing_ids)
            else:
                layers_by_id[lid] = {**layer}

    # Drop dangling layer nodeIds.
    dropped_layer_refs = 0
    for layer in layers_by_id.values():
        before = len(layer.get("nodeIds", []))
        layer["nodeIds"] = [nid for nid in layer.get("nodeIds", []) if nid in node_ids]
        dropped_layer_refs += before - len(layer["nodeIds"])

    # Project metadata: merge.
    languages: list[str] = []
    frameworks: list[str] = []
    descriptions: list[str] = []
    latest_at = ""
    latest_hash = ""
    project_name = ""

    for g in graphs:
        proj = g.get("project", {})
        project_name = proj.get("name", "") or project_name
        for lang in proj.get("languages", []):
            if lang not in languages:
                languages.append(lang)
        for fw in proj.get("frameworks", []):
            if fw not in frameworks:
                frameworks.append(fw)
        desc = proj.get("description", "")
        if desc and desc not in descriptions:
            descriptions.append(desc)
        analyzed = proj.get("analyzedAt", "")
        if analyzed > latest_at:
            latest_at = analyzed
            latest_hash = proj.get("gitCommitHash", latest_hash)

    # Build report.
    report: list[str] = []
    report.append(
        f"Input: {total_input_nodes} nodes, {total_input_edges} edges (from {len(graphs)} graphs)"
    )

    fixed_lines: list[str] = []
    if node_dedup_by_type:
        for ntype, count in node_dedup_by_type.most_common():
            fixed_lines.append(f"  {count:>4} × duplicate '{ntype}' nodes removed (kept later)")
    if edge_dedup_count:
        fixed_lines.append(f"  {edge_dedup_count:>4} × duplicate edges removed (kept higher weight)")
    if dropped_layer_refs:
        fixed_lines.append(f"  {dropped_layer_refs:>4} × dangling layer nodeId refs removed")

    if fixed_lines:
        total_fixed = sum(node_dedup_by_type.values()) + edge_dedup_count + dropped_layer_refs
        report.append("")
        report.append(f"Fixed ({total_fixed} corrections):")
        report.extend(fixed_lines)

    if unfixable:
        report.append("")
        report.append(f"Could not fix ({len(unfixable)} issues — needs agent review):")
        for detail in unfixable:
            report.append(f"  - {detail}")

    report.append("")
    report.append(
        f"Output: {len(nodes_by_id)} nodes, {len(valid_edges)} edges, {len(layers_by_id)} layers"
    )

    merged: dict[str, Any] = {
        "version": "1.0.0",
        "project": {
            "name": project_name,
            "languages": languages,
            "frameworks": frameworks,
            "description": " | ".join(descriptions)
            if len(descriptions) > 1
            else (descriptions[0] if descriptions else ""),
            "analyzedAt": latest_at,
            "gitCommitHash": latest_hash,
        },
        "nodes": list(nodes_by_id.values()),
        "edges": valid_edges,
        "layers": list(layers_by_id.values()),
    }

    return merged, report


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m understand_core.merge_subdomain_graphs <project-root> [file1.json ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    project_root = Path(sys.argv[1]).resolve()
    ua_dir = project_root / ".understand-anything"

    if not ua_dir.is_dir():
        print(f"Error: {ua_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    output_path = ua_dir / "knowledge-graph.json"

    if len(sys.argv) > 2:
        graph_files = [Path(f).resolve() for f in sys.argv[2:]]
    else:
        # Auto-discover, restricted to the user's selected parts.
        graph_files = select_partition_graphs(project_root)

    if not graph_files:
        print("No subdomain graphs found to merge", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(graph_files)} subdomain graphs:", file=sys.stderr)
    for f in graph_files:
        print(f"  - {f.name}", file=sys.stderr)

    graphs: list[dict[str, Any]] = []
    for f in graph_files:
        g = load_graph(f)
        if g is not None:
            graphs.append(g)
            print(
                f"    Loaded {f.name}: {len(g.get('nodes', []))} nodes, {len(g.get('edges', []))} edges",
                file=sys.stderr,
            )

    if not graphs:
        print("Error: no valid subdomain graphs loaded", file=sys.stderr)
        sys.exit(1)

    if output_path.exists():
        base = load_graph(output_path)
        if base:
            print(
                f"    Loaded base knowledge-graph.json: {len(base.get('nodes', []))} nodes, "
                f"{len(base.get('edges', []))} edges",
                file=sys.stderr,
            )
            graphs.insert(0, base)  # Base first — subdomain data wins on conflict.

    merged, report = merge_graphs(graphs)

    print("", file=sys.stderr)
    for line in report:
        print(line, file=sys.stderr)

    output_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    size_kb = output_path.stat().st_size / 1024
    print(f"\nWritten to {output_path} ({size_kb:.0f} KB)", file=sys.stderr)

    _maybe_write_embeddings(project_root, merged.get("nodes", []))


def _maybe_write_embeddings(project_root: Path, nodes: list[dict[str, Any]]) -> None:
    """Generate embeddings alongside the graph when an API key is configured.

    Opt-in and best-effort: a missing key skips silently and any failure is
    logged without aborting the run (absence of the file is a clean
    "semantic search unavailable" signal for the dashboard).
    """
    from understand_core import embeddings

    if not embeddings.embeddings_enabled():
        return
    try:
        out = embeddings.generate_and_save(project_root, nodes)
        print(f"Wrote embeddings to {out}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 — never fail the pipeline on embeddings
        print(f"Embedding generation skipped: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
