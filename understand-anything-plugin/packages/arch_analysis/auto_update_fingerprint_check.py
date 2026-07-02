"""Auto-update Phase 1 — structural fingerprint check (zero LLM tokens).

Reads ``auto-update-state.json`` and ``fingerprints.json``, classifies every
changed source file against its stored fingerprint, derives the overall update
decision, and writes ``change-analysis.json``. On a ``SKIP`` decision it bumps
``meta.json`` to the current commit (no LLM work needed).

Usage:
    python -m arch_analysis.auto_update_fingerprint_check <project-root>

Input:  intermediate/auto-update-state.json, fingerprints.json, knowledge-graph.json
Output: intermediate/change-analysis.json
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import auto_update_common as c
from .fingerprints import classify_file_change, classify_update, load_fingerprint_store


def run(project_root: Path) -> dict:
    """Run the fingerprint check and return the ``ChangeAnalysis`` dict."""
    state = c.read_json(c.state_path(project_root))
    if not isinstance(state, dict):
        raise FileNotFoundError("auto-update-state.json missing or unreadable")

    changed = list(state.get("changedSourceFiles", []))
    current_commit = state.get("currentCommit")

    store, _ = load_fingerprint_store(c.fingerprints_path(project_root))
    stored_files: dict = store.get("files", {}) if isinstance(store, dict) else {}

    graph = c.read_json(c.graph_path(project_root))
    graph_paths = c.graph_file_paths(graph)

    file_changes: list[dict] = []
    for rel in changed:
        file_changes.append(
            classify_file_change(project_root, rel, stored_files.get(rel))
        )

    decision = classify_update(file_changes, graph_paths)

    structural = [f for f in file_changes if f["changeLevel"] == "STRUCTURAL"]
    deleted = [f for f in structural if f["status"] == "deleted"]
    new = [f for f in structural if f["status"] == "new"]
    # Files to reanalyze = structural files still present on disk.
    files_to_reanalyze = sorted(
        f["filePath"] for f in structural if f["status"] != "deleted"
    )

    analysis = {
        "action": decision["action"],
        "rerunArchitecture": decision["rerunArchitecture"],
        "reason": decision["reason"],
        "filesToReanalyze": files_to_reanalyze,
        "newFiles": sorted(f["filePath"] for f in new),
        "deletedFiles": sorted(f["filePath"] for f in deleted),
        "cosmeticOnlyFiles": sorted(
            f["filePath"] for f in file_changes if f["changeLevel"] == "COSMETIC"
        ),
        "unchangedFiles": sorted(
            f["filePath"] for f in file_changes if f["changeLevel"] == "NONE"
        ),
        "fileChanges": file_changes,
        "metadataUpdated": False,
    }

    # On SKIP there is no structural work — bump metadata to the new commit.
    if decision["action"] == "SKIP" and current_commit:
        c.write_meta(project_root, current_commit)
        analysis["metadataUpdated"] = True

    return analysis


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write(
            "Usage: python -m arch_analysis.auto_update_fingerprint_check <project-root>\n"
        )
        return 1

    project_root = Path(args[0]).resolve()
    try:
        analysis = run(project_root)
    except FileNotFoundError as err:
        sys.stderr.write(f"auto_update_fingerprint_check failed: {err}\n")
        return 1

    c.write_json(c.change_analysis_path(project_root), analysis)
    c.emit(analysis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
