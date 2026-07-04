"""Update classification — port of ``packages/core/src/change-classifier.ts``.

arch_analysis.fingerprints.classify_update covers the same decision matrix but
takes a different signature (per-file dicts + graph path set). The core/dashboard
contract consumes the :class:`~understand_core.fingerprint.ChangeAnalysis`
partition shape and ``(totalFilesInGraph, allKnownFiles)`` args, with TS-specific
reason strings the tests assert, so we port that surface faithfully here.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from .fingerprint import ChangeAnalysis

UpdateAction = Literal["SKIP", "PARTIAL_UPDATE", "ARCHITECTURE_UPDATE", "FULL_UPDATE"]


class UpdateDecision(TypedDict):
    action: UpdateAction
    filesToReanalyze: list[str]
    rerunArchitecture: bool
    reason: str


def classify_update(
    analysis: ChangeAnalysis,
    total_files_in_graph: int,
    all_known_files: list[str] | None = None,
) -> UpdateDecision:
    """Classify the type of graph update needed from a change analysis.

    - SKIP: all files NONE or COSMETIC only
    - PARTIAL_UPDATE: some STRUCTURAL, same directories
    - ARCHITECTURE_UPDATE: new/deleted directories or >10 structural files
    - FULL_UPDATE: >30 structural files or >50% of total files changed structurally
    """
    if all_known_files is None:
        all_known_files = []

    new_files = analysis["newFiles"]
    deleted_files = analysis["deletedFiles"]
    structurally_changed = analysis["structurallyChangedFiles"]
    cosmetic_only = analysis["cosmeticOnlyFiles"]

    structural_count = len(structurally_changed) + len(new_files) + len(deleted_files)

    # No structural changes — skip
    if structural_count == 0:
        cosmetic_count = len(cosmetic_only)
        reason = (
            f"{cosmetic_count} file(s) have cosmetic-only changes (no structural impact)"
            if cosmetic_count > 0
            else "No changes detected"
        )
        return {
            "action": "SKIP",
            "filesToReanalyze": [],
            "rerunArchitecture": False,
            "reason": reason,
        }

    # Too many structural changes — full rebuild
    triggered_by_count = structural_count > 30
    triggered_by_percentage = (
        total_files_in_graph > 0 and structural_count / total_files_in_graph > 0.5
    )
    if triggered_by_count or triggered_by_percentage:
        if triggered_by_count and triggered_by_percentage:
            threshold_reason = ">30 files and >50% of project"
        elif triggered_by_count:
            threshold_reason = ">30 files"
        else:
            threshold_reason = ">50% of project"
        return {
            "action": "FULL_UPDATE",
            "filesToReanalyze": [*structurally_changed, *new_files],
            "rerunArchitecture": True,
            "reason": (
                f"{structural_count} files have structural changes "
                f"({threshold_reason}) — full rebuild recommended"
            ),
        }

    has_directory_changes = _detect_directory_changes(
        new_files, deleted_files, all_known_files
    )

    if has_directory_changes or structural_count > 10:
        if has_directory_changes:
            reason = (
                f"Directory structure changed ({len(new_files)} new, "
                f"{len(deleted_files)} deleted files)"
            )
        else:
            reason = (
                f"{structural_count} files have structural changes "
                "— architecture re-analysis needed"
            )
        return {
            "action": "ARCHITECTURE_UPDATE",
            "filesToReanalyze": [*structurally_changed, *new_files],
            "rerunArchitecture": True,
            "reason": reason,
        }

    # Localized structural changes — partial update
    return {
        "action": "PARTIAL_UPDATE",
        "filesToReanalyze": [*structurally_changed, *new_files],
        "rerunArchitecture": False,
        "reason": f"{structural_count} file(s) have structural changes: {_summarize_changes(analysis)}",
    }


def _detect_directory_changes(
    new_files: list[str], deleted_files: list[str], all_known_files: list[str]
) -> bool:
    """Detect new/removed top-level directories from changed files."""
    existing_dirs = {d for d in (_top_directory(f) for f in all_known_files) if d}

    for f in new_files:
        d = _top_directory(f)
        if d and d not in existing_dirs:
            return True

    for f in deleted_files:
        d = _top_directory(f)
        if d and d not in existing_dirs:
            return True

    return False


def _top_directory(file_path: str) -> str | None:
    """Top-level directory of a path (first segment), mirroring Node ``dirname``."""
    dir_part = file_path.rsplit("/", 1)[0] if "/" in file_path else "."
    if dir_part in (".", ""):
        return None
    segments = dir_part.split("/")
    return segments[0] or None


def _summarize_changes(analysis: ChangeAnalysis) -> str:
    parts: list[str] = []
    if analysis["newFiles"]:
        parts.append(f"{len(analysis['newFiles'])} new")
    if analysis["deletedFiles"]:
        parts.append(f"{len(analysis['deletedFiles'])} deleted")
    if analysis["structurallyChangedFiles"]:
        parts.append(f"{len(analysis['structurallyChangedFiles'])} modified")
    return ", ".join(parts)


__all__ = ["UpdateAction", "UpdateDecision", "classify_update"]
