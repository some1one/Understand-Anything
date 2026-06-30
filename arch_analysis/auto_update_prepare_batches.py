"""Auto-update Phase 2a — prepare targeted re-analysis batches.

Reuses the ``/understand`` batching machinery (:func:`compute_batches`) on just
the changed files. Loads the preserved ``scan-result.json``, augments it with
freshly-scanned entries for new files, runs changed-file batching, and writes a
dispatch summary the LLM file-analysis phase consumes (one ``file-analyzer``
dispatch per batch).

Usage:
    python -m arch_analysis.auto_update_prepare_batches <project-root>

Input:  intermediate/change-analysis.json, intermediate/scan-result.json (if any)
Output: intermediate/batches.json, intermediate/dispatch-summary.json
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import auto_update_common as c
from .compute_batches import compute_batches
from .languages import detect_category, detect_language


def _scan_file_entry(project_root: Path, rel: str) -> dict | None:
    abs_path = project_root / rel
    try:
        size_lines = abs_path.read_bytes().count(b"\n")
    except OSError:
        return None
    return {
        "path": rel,
        "language": detect_language(rel),
        "sizeLines": size_lines,
        "fileCategory": detect_category(rel),
    }


def run(project_root: Path) -> dict:
    """Build batches + dispatch summary; return the dispatch summary dict."""
    analysis = c.read_json(c.change_analysis_path(project_root))
    if not isinstance(analysis, dict):
        raise FileNotFoundError("change-analysis.json missing or unreadable")

    files_to_reanalyze: list[str] = list(analysis.get("filesToReanalyze", []))

    # Load the preserved scan-result (full-project inventory + importMap) or
    # fall back to an empty inventory.
    scan = c.read_json(c.scan_result_path(project_root))
    if not isinstance(scan, dict):
        scan = {"files": [], "importMap": {}}
    scan.setdefault("files", [])
    scan.setdefault("importMap", {})

    known_paths = {f.get("path") for f in scan["files"] if isinstance(f, dict)}
    for rel in files_to_reanalyze:
        if rel not in known_paths:
            entry = _scan_file_entry(project_root, rel)
            if entry is not None:
                scan["files"].append(entry)
                known_paths.add(rel)

    batches_payload = compute_batches(
        project_root, scan, changed_files=set(files_to_reanalyze)
    )
    c.write_json(c.batches_path(project_root), batches_payload)

    # Project context for the file-analyzer dispatches.
    graph = c.read_json(c.graph_path(project_root))
    project = graph.get("project", {}) if isinstance(graph, dict) else {}

    batch_summaries = []
    for b in batches_payload.get("batches", []):
        idx = b["batchIndex"]
        batch_summaries.append(
            {
                "batchIndex": idx,
                "outputPath": str(
                    c.intermediate_dir(project_root) / f"batch-{idx}.json"
                ),
                "files": [
                    {
                        "path": f["path"],
                        "sizeLines": f.get("sizeLines"),
                        "language": f.get("language"),
                    }
                    for f in b["files"]
                ],
            }
        )

    summary = {
        "projectName": project.get("name"),
        "projectDescription": project.get("description"),
        "languages": project.get("languages", []),
        "frameworks": project.get("frameworks", []),
        "totalBatches": len(batch_summaries),
        "filesToReanalyze": files_to_reanalyze,
        "allProjectFiles": sorted(known_paths),
        "batches": batch_summaries,
    }
    c.write_json(c.dispatch_summary_path(project_root), summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.auto_update_prepare_batches <project-root>\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    try:
        summary = run(project_root)
    except FileNotFoundError as err:
        sys.stderr.write(f"auto_update_prepare_batches failed: {err}\n")
        return 1

    c.emit(summary)
    sys.stderr.write(
        f"prepare-batches: {summary['totalBatches']} batch(es) for "
        f"{len(summary['filesToReanalyze'])} file(s)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
