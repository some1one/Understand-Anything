"""Validate and write a file-analyzer batch's final output.

Replaces the agent's manual import-edge self-check and manual part splitting.
Given the deterministic ``context`` + ``seed`` and the LLM's edited ``draft``,
the finalizer:

  1. Schema-validates the draft against ``graph-fragment.schema.json``.
  2. Verifies every seeded node, every seeded tag, and every seeded edge
     survived the LLM's edits.
  3. Enforces exact ``imports`` edge coverage against ``batchImportData``.
  4. Verifies every edge endpoint is either in-batch or an allowed cross-batch
     reference derived from the context (import targets + ``neighborMap``).
  5. Splits the fragment into ``batch-<N>.json`` / ``batch-<N>-part-<K>.json``
     using the documented size thresholds and writes them to ``intermediate/``.

Exit code is ``0`` only when every check passes and the files are written;
``1`` (with issues on stderr) otherwise, so the agent fails hard.

Usage:
    python -m arch_analysis.finalize_file_batch_output <project-root> <context.json> <seed.json> <draft.json>
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from .schema import SchemaValidationError, validate_graph_fragment

_MAX_NODES_PER_PART = 60
_MAX_EDGES_PER_PART = 120


def _node_path(node: dict[str, Any]) -> str | None:
    fp = node.get("filePath")
    if isinstance(fp, str) and fp:
        return fp
    nid = node.get("id", "")
    parts = nid.split(":")
    return parts[1] if len(parts) >= 2 else None


def _allowed_cross_batch_ids(context: dict[str, Any]) -> set[str]:
    """Node ids reachable as cross-batch edge targets per the context."""
    allowed: set[str] = set()
    # Import targets are verified project-internal file paths.
    for targets in (context.get("batchImportData") or {}).values():
        if isinstance(targets, list):
            for tgt in targets:
                if isinstance(tgt, str) and tgt:
                    allowed.add(f"file:{tgt}")
    # neighborMap neighbors: their file node and any exported symbol nodes.
    for neighbors in (context.get("neighborMap") or {}).values():
        if not isinstance(neighbors, list):
            continue
        for nb in neighbors:
            if not isinstance(nb, dict):
                continue
            npath = nb.get("path")
            if not isinstance(npath, str):
                continue
            allowed.add(f"file:{npath}")
            for sym in nb.get("symbols", []) or []:
                if isinstance(sym, str) and sym:
                    allowed.add(f"function:{npath}:{sym}")
                    allowed.add(f"class:{npath}:{sym}")
    return allowed


def validate_draft(
    context: dict[str, Any],
    seed: dict[str, Any],
    draft: dict[str, Any],
) -> list[str]:
    """Return a list of issue strings; empty means the draft is valid."""
    issues: list[str] = []

    try:
        validate_graph_fragment(draft)
    except SchemaValidationError as err:
        return [f"draft schema validation failed: {err}"]

    draft_nodes = draft.get("nodes", [])
    draft_edges = draft.get("edges", [])

    draft_node_ids = {n["id"] for n in draft_nodes if isinstance(n, dict) and n.get("id")}
    draft_tags_by_id: dict[str, set[str]] = {
        n["id"]: set(n.get("tags") or [])
        for n in draft_nodes
        if isinstance(n, dict) and n.get("id")
    }
    draft_edge_keys = {
        (e.get("source"), e.get("target"), e.get("type"))
        for e in draft_edges
        if isinstance(e, dict)
    }

    # ── Seed preservation: nodes + tags ──────────────────────────────────
    for sn in seed.get("nodes", []):
        sid = sn.get("id")
        if sid not in draft_node_ids:
            issues.append(f"seeded node '{sid}' is missing from the draft")
            continue
        missing_tags = set(sn.get("tags") or []) - draft_tags_by_id.get(sid, set())
        if missing_tags:
            issues.append(
                f"seeded node '{sid}' is missing required tag(s): "
                f"{sorted(missing_tags)}"
            )

    # ── Seed preservation: edges ─────────────────────────────────────────
    for se in seed.get("edges", []):
        key = (se.get("source"), se.get("target"), se.get("type"))
        if key not in draft_edge_keys:
            issues.append(
                f"seeded {se.get('type')} edge {se.get('source')} → "
                f"{se.get('target')} is missing from the draft"
            )

    # ── Exact imports coverage ───────────────────────────────────────────
    batch_import_data = context.get("batchImportData") or {}
    required_imports: set[tuple[str, str]] = set()
    for src_path, targets in batch_import_data.items():
        if not isinstance(targets, list):
            continue
        for tgt in targets:
            if isinstance(tgt, str) and tgt and tgt != src_path:
                required_imports.add((f"file:{src_path}", f"file:{tgt}"))

    present_imports = {
        (e.get("source"), e.get("target"))
        for e in draft_edges
        if isinstance(e, dict) and e.get("type") == "imports"
    }
    batch_file_ids = {f"file:{p}" for p in batch_import_data.keys()}

    for req in sorted(required_imports):
        if req not in present_imports:
            issues.append(f"missing imports edge {req[0]} → {req[1]}")
    # Exactness: a batch-file-sourced imports edge must be in the required set.
    for src, tgt in sorted(present_imports):
        if src in batch_file_ids and (src, tgt) not in required_imports:
            issues.append(
                f"spurious imports edge {src} → {tgt} not present in batchImportData"
            )

    # ── Cross-batch reference validity ───────────────────────────────────
    allowed_targets = draft_node_ids | _allowed_cross_batch_ids(context)
    for i, e in enumerate(draft_edges):
        if not isinstance(e, dict):
            continue
        src, tgt = e.get("source"), e.get("target")
        if src not in draft_node_ids:
            issues.append(
                f"edge[{i}] {src} → {tgt}: source is not a node defined in this batch"
            )
        if tgt not in allowed_targets:
            issues.append(
                f"edge[{i}] {src} → {tgt}: target is neither in-batch nor an "
                f"allowed cross-batch reference (import target or neighborMap symbol)"
            )

    return issues


def split_into_parts(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    batch_files: list[str],
) -> list[dict[str, Any]]:
    """Partition a fragment into 1+ parts per the documented thresholds."""
    if len(nodes) <= _MAX_NODES_PER_PART and len(edges) <= _MAX_EDGES_PER_PART:
        return [{"nodes": nodes, "edges": edges}]

    parts = max(
        1,
        math.ceil(
            max(len(nodes) / _MAX_NODES_PER_PART, len(edges) / _MAX_EDGES_PER_PART)
        ),
    )
    ordered_files = sorted(batch_files)
    per_part = math.ceil(len(ordered_files) / parts) if ordered_files else 0

    # file path → part index.
    part_of_file: dict[str, int] = {}
    for i, fp in enumerate(ordered_files):
        part_of_file[fp] = (i // per_part) if per_part else 0

    def part_for_node(node: dict[str, Any]) -> int:
        path = _node_path(node)
        return part_of_file.get(path, 0)

    node_part: dict[str, int] = {}
    buckets_nodes: list[list[dict[str, Any]]] = [[] for _ in range(parts)]
    for node in nodes:
        p = part_for_node(node)
        if p >= parts:
            p = parts - 1
        buckets_nodes[p].append(node)
        if node.get("id"):
            node_part[node["id"]] = p

    buckets_edges: list[list[dict[str, Any]]] = [[] for _ in range(parts)]
    for edge in edges:
        p = node_part.get(edge.get("source"), 0)
        buckets_edges[p].append(edge)

    return [
        {"nodes": buckets_nodes[i], "edges": buckets_edges[i]} for i in range(parts)
    ]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 4:
        sys.stderr.write(
            "Usage: python -m arch_analysis.finalize_file_batch_output "
            "<project-root> <context.json> <seed.json> <draft.json>\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    try:
        context = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        seed = json.loads(Path(args[2]).read_text(encoding="utf-8"))
        draft = json.loads(Path(args[3]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"finalize_file_batch_output failed: cannot read input: {err}\n")
        return 1

    issues = validate_draft(context, seed, draft)
    if issues:
        sys.stderr.write(
            f"finalize_file_batch_output: {len(issues)} issue(s) — NOT writing batch files:\n"
        )
        for issue in issues:
            sys.stderr.write(f"  - {issue}\n")
        return 1

    batch_index = context.get("batchIndex")
    if not isinstance(batch_index, int):
        sys.stderr.write("finalize_file_batch_output failed: context has no integer batchIndex\n")
        return 1

    batch_files = [
        f["path"]
        for f in context.get("batchFiles", [])
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    ]

    out_dir = project_root / ".understand-anything" / "intermediate"
    out_dir.mkdir(parents=True, exist_ok=True)

    fragments = split_into_parts(draft.get("nodes", []), draft.get("edges", []), batch_files)

    written: list[str] = []
    if len(fragments) == 1:
        path = out_dir / f"batch-{batch_index}.json"
        path.write_text(json.dumps(fragments[0], indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path.name)
    else:
        for k, frag in enumerate(fragments, start=1):
            path = out_dir / f"batch-{batch_index}-part-{k}.json"
            path.write_text(json.dumps(frag, indent=2, ensure_ascii=False), encoding="utf-8")
            written.append(path.name)

    sys.stderr.write(
        f"finalize_file_batch_output: batch {batch_index} OK — "
        f"{len(draft.get('nodes', []))} nodes, {len(draft.get('edges', []))} edges → "
        f"{', '.join(written)}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
