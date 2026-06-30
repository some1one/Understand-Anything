"""Auto-update Phase 3 — apply layers, validate, save, patch fingerprints.

Takes the merged graph from :mod:`arch_analysis.auto_update_apply_batches` and:

1. applies architecture layers — either the architecture-analyzer's fresh
   ``layers.json`` (when ``rerunArchitecture``) or a deterministic lite update
   of the carried-forward layers (new files placed by directory match, deleted
   files removed);
2. runs lite validation cleanup (drop dangling edges, prune unknown layer ids,
   ensure every file-level node is in exactly one layer);
3. writes ``knowledge-graph.json``;
4. patches ``fingerprints.json`` (LOAD-PATCH-SAVE — never clobbers unrelated
   entries) and bumps ``meta.json``;
5. cleans intermediate files while preserving ``scan-result.json``.

Usage:
    python -m arch_analysis.auto_update_finalize <project-root>
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import auto_update_common as c
from .fingerprints import patch_and_save_fingerprints
from .validate_graph import FILE_LEVEL_TYPES, _node_file_path

CATCH_ALL_LAYER = {
    "id": "layer:misc",
    "name": "Miscellaneous",
    "description": "Files not assigned to a specific architecture layer.",
    "nodeIds": [],
}

# Files preserved across the intermediate cleanup.
_PRESERVE = frozenset({"scan-result.json", "auto-update-summary.json"})


def _dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _common_prefix_len(a: str, b: str) -> int:
    """Count of matching leading path segments between two directories."""
    sa, sb = a.split("/"), b.split("/")
    n = 0
    for x, y in zip(sa, sb):
        if x != y:
            break
        n += 1
    return n


def reconcile_layers(
    nodes: list[dict], layers: list[dict]
) -> list[dict]:
    """Drop dead ids, place unassigned file nodes, dedupe, drop empty layers."""
    node_ids = {n["id"] for n in nodes if isinstance(n, dict) and n.get("id")}
    id_to_path = {
        n["id"]: _node_file_path(n)
        for n in nodes
        if isinstance(n, dict) and n.get("id")
    }

    # Clean each layer: keep only known ids, deduped, in one layer only.
    seen: set[str] = set()
    clean_layers: list[dict] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        kept: list[str] = []
        for nid in layer.get("nodeIds", []):
            if nid in node_ids and nid not in seen:
                kept.append(nid)
                seen.add(nid)
        new_layer = dict(layer)
        new_layer["nodeIds"] = kept
        clean_layers.append(new_layer)

    # Place file-level nodes not yet in any layer by directory similarity.
    unassigned = [
        n
        for n in nodes
        if isinstance(n, dict)
        and n.get("type") in FILE_LEVEL_TYPES
        and n.get("id")
        and n["id"] not in seen
    ]
    catch_all: dict | None = None
    for n in unassigned:
        path = id_to_path.get(n["id"]) or ""
        ndir = _dir_of(path)
        best_layer, best_score = None, -1
        for layer in clean_layers:
            for mid in layer["nodeIds"]:
                mp = id_to_path.get(mid)
                if not mp:
                    continue
                score = _common_prefix_len(ndir, _dir_of(mp))
                if score > best_score:
                    best_score, best_layer = score, layer
        if best_layer is None or best_score <= 0:
            if catch_all is None:
                catch_all = dict(CATCH_ALL_LAYER)
                catch_all["nodeIds"] = []
                clean_layers.append(catch_all)
            best_layer = catch_all
        best_layer["nodeIds"].append(n["id"])
        seen.add(n["id"])

    # Drop layers that ended up empty.
    return [layer for layer in clean_layers if layer["nodeIds"]]


def clean_graph(graph: dict) -> None:
    """Drop dangling edges in place (source/target not in the node set)."""
    node_ids = {n["id"] for n in graph["nodes"] if isinstance(n, dict) and n.get("id")}
    graph["edges"] = [
        e
        for e in graph["edges"]
        if isinstance(e, dict)
        and e.get("source") in node_ids
        and e.get("target") in node_ids
    ]


def _cleanup_intermediate(project_root: Path) -> None:
    intermediate = c.intermediate_dir(project_root)
    if not intermediate.is_dir():
        return
    for entry in intermediate.iterdir():
        if entry.is_file() and entry.name not in _PRESERVE:
            try:
                entry.unlink()
            except OSError:
                pass


def run(project_root: Path) -> dict:
    """Finalize the update; return the ``AutoUpdateSummary`` dict."""
    analysis = c.read_json(c.change_analysis_path(project_root)) or {}
    merged = c.read_json(c.merged_graph_path(project_root))
    if not isinstance(merged, dict):
        raise FileNotFoundError("merged-graph.json missing or unreadable")

    state = c.read_json(c.state_path(project_root)) or {}
    current_commit = state.get("currentCommit") or analysis.get("currentCommit")

    # 1. Layers — fresh (architecture rerun) or carried-forward (lite).
    if analysis.get("rerunArchitecture"):
        fresh = c.read_json(c.layers_path(project_root))
        layers = fresh if isinstance(fresh, list) else merged.get("layers", [])
    else:
        layers = merged.get("layers", [])

    merged["layers"] = reconcile_layers(merged["nodes"], layers)

    # 2. Lite validation cleanup.
    clean_graph(merged)

    # 3. Save the knowledge graph.
    c.write_json(c.graph_path(project_root), merged)

    # 4. Patch fingerprints (changed + deleted) then bump meta.
    changed = list(analysis.get("filesToReanalyze", [])) + list(
        analysis.get("deletedFiles", [])
    )
    before = after = 0
    try:
        before, after = patch_and_save_fingerprints(
            c.fingerprints_path(project_root),
            project_root,
            changed,
            git_commit_hash=current_commit,
        )
    except RuntimeError as err:
        # Refused to clobber the store — surface and skip the meta bump so the
        # next run still sees work to do (fail safe).
        sys.stderr.write(f"finalize: fingerprint patch aborted: {err}\n")
        raise

    file_count = len(c.graph_file_paths(merged))
    metadata_updated = False
    if current_commit:
        c.write_meta(project_root, current_commit, analyzed_files=file_count)
        metadata_updated = True

    file_changes = analysis.get("fileChanges", [])
    summary = {
        "status": "UPDATED",
        "action": analysis.get("action", "PARTIAL_UPDATE"),
        "reason": analysis.get("reason", ""),
        "filesChecked": len(file_changes),
        "structuralChanges": sum(
            1 for f in file_changes if f.get("changeLevel") == "STRUCTURAL"
        ),
        "cosmeticOnly": sum(
            1 for f in file_changes if f.get("changeLevel") == "COSMETIC"
        ),
        "newFiles": len(analysis.get("newFiles", [])),
        "deletedFiles": len(analysis.get("deletedFiles", [])),
        "nodesUpdated": len(merged["nodes"]),
        "totalNodes": len(merged["nodes"]),
        "totalEdges": len(merged["edges"]),
        "metadataUpdated": metadata_updated,
        "outputPath": str(c.graph_path(project_root)),
    }
    sys.stderr.write(f"finalize: fingerprints {before} → {after}\n")

    # 5. Write the summary, then clean intermediate (summary preserved).
    c.write_json(c.summary_path(project_root), summary)
    _cleanup_intermediate(project_root)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.auto_update_finalize <project-root>\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    try:
        summary = run(project_root)
    except (FileNotFoundError, RuntimeError) as err:
        sys.stderr.write(f"auto_update_finalize failed: {err}\n")
        return 1

    c.emit(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
