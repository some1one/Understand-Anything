"""Phase 1.5 of /understand — community detection + batching.

Python port of ``skills/understand/compute-batches.mjs``. Reads
``scan-result.json``, runs networkx Louvain community detection on the import
graph, and writes ``batches.json`` (batches + neighborMap).

Usage:
    python -m arch_analysis.compute_batches <project-root> [--changed-files PATH]

Input:  <project-root>/.understand-anything/intermediate/scan-result.json
Output: <project-root>/.understand-anything/intermediate/batches.json
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import networkx as nx

from .treesitter import get_parser, SUPPORTED_LANGUAGES

# Deterministic seed so repeated runs partition identically.
_LOUVAIN_SEED = 42
MAX_COMMUNITY_SIZE = 35
MIN_BATCH_SIZE = 3
MAX_MERGE_TARGET = 25
MAX_NEIGHBORS = 50
MAX_E = 20  # max files per Group-E non-code parent-dir batch


# ---------------------------------------------------------------------------
# Export-name extraction (best-effort context hints for neighborMap symbols).
# ---------------------------------------------------------------------------

# Top-level tree-sitter node types whose `name` child is a useful exported
# symbol. Best-effort and language-tolerant: errors fall back to [].
_NAME_NODE_TYPES: frozenset[str] = frozenset(
    {
        "function_declaration",
        "function_definition",
        "method_declaration",
        "class_declaration",
        "class_definition",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "struct_item",
        "enum_item",
        "trait_item",
        "function_item",
        "type_declaration",
        "type_spec",
        "const_declaration",
        "lexical_declaration",
        "variable_declaration",
        "export_statement",
        "module",
    }
)


def _collect_names(node, source: bytes, out: list[str], depth: int = 0) -> None:
    if depth > 2:
        return
    for child in node.children:
        if child.type in _NAME_NODE_TYPES:
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                out.append(source[name_node.start_byte : name_node.end_byte].decode("utf-8", "replace"))
            # Descend into export/declaration wrappers to reach the real decl.
            if child.type in ("export_statement", "lexical_declaration", "variable_declaration", "const_declaration"):
                _collect_names(child, source, out, depth + 1)
        elif child.type in ("variable_declarator", "init_declarator"):
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                out.append(source[name_node.start_byte : name_node.end_byte].decode("utf-8", "replace"))


def extract_export_names(language: str, source: str) -> list[str]:
    """Best-effort top-level symbol names for a code file. Never raises."""
    if language not in SUPPORTED_LANGUAGES:
        return []
    parser = get_parser(language)
    if parser is None:
        return []
    try:
        tree = parser.parse(source.encode("utf-8"))
        names: list[str] = []
        _collect_names(tree.root_node, source.encode("utf-8"), names)
        # De-dup preserving order.
        seen: set[str] = set()
        result: list[str] = []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                result.append(n)
        return result
    except Exception:
        return []


def extract_exports(project_root: Path, code_files: list[dict]) -> dict[str, list[str]]:
    """Map each code file path to its top-level exported symbol names."""
    exports_by_path: dict[str, list[str]] = {}
    for f in code_files:
        path = f["path"]
        abs_path = project_root / path
        try:
            content = abs_path.read_text(encoding="utf-8")
        except OSError as err:
            sys.stderr.write(
                f"Warning: compute-batches: exports extraction failed for {path} "
                f"(read error: {err}) — symbols=[] in neighborMap\n"
            )
            exports_by_path[path] = []
            continue
        exports_by_path[path] = extract_export_names(f.get("language", ""), content)
    return exports_by_path


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------


def run_louvain(code_files: list[dict], import_map: dict[str, list[str]]) -> dict[str, str]:
    """Map path -> community id via networkx Louvain. May raise."""
    if os.environ.get("UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW") == "1":
        raise RuntimeError("forced throw via UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW")
    g = nx.Graph()
    paths = {f["path"] for f in code_files}
    for p in paths:
        g.add_node(p)
    for src, targets in import_map.items():
        if src not in paths:
            continue
        for tgt in targets:
            if tgt not in paths or src == tgt:
                continue
            g.add_edge(src, tgt)

    communities = nx.community.louvain_communities(g, seed=_LOUVAIN_SEED)
    # Sort communities deterministically (by size desc, then min member) and
    # assign stable ids.
    ordered = sorted(communities, key=lambda c: (-len(c), min(c)))
    out: dict[str, str] = {}
    for idx, community in enumerate(ordered):
        for node in community:
            out[node] = f"louvain_{idx}"
    return out


def count_based_assignment(code_files: list[dict], batch_size: int = 12) -> dict[str, str]:
    """Deterministic alphabetical chunking fallback when Louvain fails."""
    out: dict[str, str] = {}
    sorted_paths = sorted(f["path"] for f in code_files)
    for i, path in enumerate(sorted_paths):
        out[path] = f"count_{i // batch_size}"
    return out


# ---------------------------------------------------------------------------
# Non-code batching (Groups A–E)
# ---------------------------------------------------------------------------


def _dir_of(p: str) -> str:
    return p[: p.rfind("/")] if "/" in p else ""


def _base_of(p: str) -> str:
    return p[p.rfind("/") + 1 :] if "/" in p else p


def build_non_code_batches(non_code_files: list[dict]) -> list[dict]:
    """Build non-code batches per Groups A–E. Returns [{files, mergeable}]."""
    by_path = {f["path"]: f for f in non_code_files}
    consumed: set[str] = set()
    groups: list[dict] = []

    # Group A: per-directory Dockerfile clusters.
    dirs_with_dockerfile = sorted(
        {_dir_of(p) for p in by_path if _base_of(p) == "Dockerfile"}
    )
    for d in dirs_with_dockerfile:
        in_dir = [p for p in by_path if _dir_of(p) == d]
        cluster = [
            p
            for p in in_dir
            if _base_of(p) in ("Dockerfile", ".dockerignore")
            or _base_of(p).startswith("docker-compose.")
        ]
        if cluster:
            groups.append({"files": [by_path[p] for p in cluster], "mergeable": False})
            consumed.update(cluster)

    # Group B: .github/workflows/*
    gh = [
        p
        for p in by_path
        if p.startswith(".github/workflows/")
        and (p.endswith(".yml") or p.endswith(".yaml"))
        and p not in consumed
    ]
    if gh:
        groups.append({"files": [by_path[p] for p in gh], "mergeable": False})
        consumed.update(gh)

    # Group C: .gitlab-ci.yml + .circleci/*
    ci = [
        p
        for p in by_path
        if (p == ".gitlab-ci.yml" or p.startswith(".circleci/")) and p not in consumed
    ]
    if ci:
        groups.append({"files": [by_path[p] for p in ci], "mergeable": False})
        consumed.update(ci)

    # Group D: SQL migrations per migrations/ or migration/ directory.
    migration_re = re.compile(r"(^|/)migrations?$")
    migration_dirs = {
        _dir_of(p)
        for p in by_path
        if p.endswith(".sql") and migration_re.search(_dir_of(p))
    }
    for d in migration_dirs:
        sqls = sorted(
            p
            for p in by_path
            if _dir_of(p) == d and p.endswith(".sql") and p not in consumed
        )
        if sqls:
            groups.append({"files": [by_path[p] for p in sqls], "mergeable": False})
            consumed.update(sqls)

    # Group E: remaining grouped by immediate parent dir, max MAX_E per batch.
    remaining_by_dir: dict[str, list[str]] = {}
    for p in sorted(by_path):
        if p in consumed:
            continue
        remaining_by_dir.setdefault(_dir_of(p), []).append(p)
    for paths in remaining_by_dir.values():
        for i in range(0, len(paths), MAX_E):
            slice_ = paths[i : i + MAX_E]
            groups.append({"files": [by_path[p] for p in slice_], "mergeable": True})

    return groups


def merge_small_batches(bare_batches: list[dict]) -> list[dict]:
    """Pool small mergeable batches into 'misc' batches. Returns renumbered list."""
    keepers: list[dict] = []
    small_mergeable: list[dict] = []
    for b in bare_batches:
        if b.get("mergeable") and len(b["files"]) < MIN_BATCH_SIZE:
            small_mergeable.append(b)
        else:
            keepers.append(b)

    if not small_mergeable:
        return [{"batchIndex": i + 1, "files": b["files"]} for i, b in enumerate(keepers)]

    pooled = [f for b in small_mergeable for f in b["files"]]
    pooled.sort(key=lambda f: f["path"])

    misc: list[dict] = []
    for i in range(0, len(pooled), MAX_MERGE_TARGET):
        misc.append({"files": pooled[i : i + MAX_MERGE_TARGET]})

    sys.stderr.write(
        f"Info: compute-batches: merged {len(small_mergeable)} small batches "
        f"({len(pooled)} files) into {len(misc)} misc batches "
        f"— singletons and orphans consolidated\n"
    )

    final = keepers + misc
    return [{"batchIndex": i + 1, "files": b["files"]} for i, b in enumerate(final)]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def compute_batches(
    project_root: Path, scan: dict, changed_files: set[str] | None = None
) -> dict[str, Any]:
    """Compute the batches payload from a loaded scan-result dict."""
    files = scan.get("files", [])
    code_files = [f for f in files if f.get("fileCategory") == "code"]
    non_code_files = [f for f in files if f.get("fileCategory") != "code"]
    import_map: dict[str, list[str]] = scan.get("importMap", {})

    sys.stderr.write(f"Loaded {len(files)} files ({len(code_files)} code).\n")

    exports_by_path = extract_exports(project_root, code_files)

    algorithm = "louvain"
    try:
        per_file_community = run_louvain(code_files, import_map)
    except Exception as err:
        sys.stderr.write(
            f"Warning: compute-batches: Louvain failed ({err}) "
            f"— falling back to count-based grouping (12 files/batch)\n"
        )
        per_file_community = count_based_assignment(code_files, 12)
        algorithm = "count-fallback"

    files_by_community: dict[str, list[str]] = {}
    for path, cid in per_file_community.items():
        files_by_community.setdefault(cid, []).append(path)

    split_communities: dict[str, list[str]] = {}
    next_synth = 0
    if algorithm == "louvain":
        for cid, paths in files_by_community.items():
            if len(paths) <= MAX_COMMUNITY_SIZE:
                split_communities[cid] = paths
                continue
            sys.stderr.write(
                f"Warning: compute-batches: community size {len(paths)} > max "
                f"{MAX_COMMUNITY_SIZE} — splitting via alphabetical chunking\n"
            )
            ordered = sorted(paths)
            parts = math.ceil(len(paths) / MAX_COMMUNITY_SIZE)
            per_part = math.ceil(len(paths) / parts)
            for i in range(parts):
                slice_ = ordered[i * per_part : (i + 1) * per_part]
                split_communities[f"__split_{cid}_{next_synth}"] = slice_
                next_synth += 1
    else:
        split_communities = dict(files_by_community)

    sorted_communities = sorted(
        split_communities.items(),
        key=lambda kv: (-len(kv[1]), min(kv[1]) if kv[1] else ""),
    )

    file_meta_by_path = {f["path"]: f for f in files}

    code_bare = [
        {
            "batchIndex": idx + 1,
            "files": [file_meta_by_path[p] for p in sorted(paths)],
            "mergeable": True,
        }
        for idx, (_, paths) in enumerate(sorted_communities)
    ]
    non_code_groups = build_non_code_batches(non_code_files)
    non_code_bare = [
        {
            "batchIndex": len(code_bare) + i + 1,
            "files": g["files"],
            "mergeable": g["mergeable"],
        }
        for i, g in enumerate(non_code_groups)
    ]
    bare_batches = code_bare + non_code_bare
    merged_bare = merge_small_batches(bare_batches)

    batch_of: dict[str, int] = {}
    for b in merged_bare:
        for f in b["files"]:
            batch_of[f["path"]] = b["batchIndex"]

    reverse_import_map: dict[str, list[str]] = {}
    for src, targets in import_map.items():
        for tgt in targets:
            reverse_import_map.setdefault(tgt, []).append(src)

    neighbor_degree: dict[str, int] = {}
    for f in code_files:
        out_deg = len(import_map.get(f["path"], []))
        in_deg = len(reverse_import_map.get(f["path"], []))
        neighbor_degree[f["path"]] = out_deg + in_deg

    batches: list[dict] = []
    for b in merged_bare:
        batch_paths = {f["path"] for f in b["files"]}
        batch_import_data: dict[str, list[str]] = {}
        neighbor_map: dict[str, list[dict]] = {}
        for f in b["files"]:
            path = f["path"]
            batch_import_data[path] = list(import_map.get(path, []))

            out_neighbors = import_map.get(path, [])
            in_neighbors = reverse_import_map.get(path, [])
            all_neighbors = set(out_neighbors) | set(in_neighbors)
            raw_count = len(all_neighbors)
            filtered = [p for p in all_neighbors if p in batch_of and p not in batch_paths]

            kept = [
                {"path": p, "batchIndex": batch_of[p], "symbols": exports_by_path.get(p, [])}
                for p in filtered
            ]

            if raw_count > MAX_NEIGHBORS:
                kept.sort(
                    key=lambda k: (-neighbor_degree.get(k["path"], 0), k["path"])
                )
                before = len(kept)
                kept = kept[:MAX_NEIGHBORS]
                sys.stderr.write(
                    f"Warning: compute-batches: neighborMap for {path} has high "
                    f"1-hop degree {raw_count} — exceeds soft cap of {MAX_NEIGHBORS} "
                    f"— keeping top {len(kept)} ({before - len(kept)} dropped)\n"
                )
            else:
                kept.sort(key=lambda k: k["path"])

            if kept:
                neighbor_map[path] = kept

        batches.append(
            {
                "batchIndex": b["batchIndex"],
                "files": b["files"],
                "batchImportData": batch_import_data,
                "neighborMap": neighbor_map,
            }
        )

    final_batches = batches
    if changed_files is not None:
        final_batches = [
            b for b in batches if any(f["path"] in changed_files for f in b["files"])
        ]

    return {
        "schemaVersion": 1,
        "algorithm": algorithm,
        "totalFiles": len(files),
        "totalBatches": len(final_batches),
        "exportsByPath": exports_by_path,
        "batches": final_batches,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.compute_batches <project-root> "
            "[--changed-files PATH]\n"
        )
        return 1

    project_root = Path(args[0]).resolve()

    changed_files: set[str] | None = None
    rest = args[1:]
    i = 0
    while i < len(rest):
        arg = rest[i]
        m = re.match(r"^--changed-files=(.+)$", arg)
        path_val: str | None = None
        if m:
            path_val = m.group(1)
        elif arg == "--changed-files" and i + 1 < len(rest):
            path_val = rest[i + 1]
            i += 1
        if path_val is not None:
            try:
                content = Path(path_val).read_text(encoding="utf-8")
            except OSError as err:
                sys.stderr.write(
                    f"Error: compute-batches: --changed-files path not readable: "
                    f"{path_val} ({err})\n"
                )
                return 1
            changed_files = {ln.strip() for ln in content.splitlines() if ln.strip()}
        i += 1

    scan_path = project_root / ".understand-anything" / "intermediate" / "scan-result.json"
    if not scan_path.exists():
        sys.stderr.write(f"Error: scan-result.json not found at {scan_path}\n")
        return 1

    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    output = compute_batches(project_root, scan, changed_files)

    out_path = project_root / ".understand-anything" / "intermediate" / "batches.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    sizes = [len(b["files"]) for b in output["batches"]]
    sys.stderr.write(
        f"Wrote {len(output['batches'])} batches "
        f"(sizes: max={max(sizes) if sizes else 0}, min={min(sizes) if sizes else 0}) "
        f"to {out_path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
