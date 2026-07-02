"""Shared structural-fingerprint logic for the auto-update pipeline.

This is the deterministic core that ``build_fingerprints`` (the ``/understand``
Phase 7 baseline) and the ``auto_update_*`` commands both build on. It owns:

- content hashing (SHA-256 of file bytes),
- structural fingerprint extraction from a tree-sitter analysis,
- fingerprint comparison + update classification (NONE / COSMETIC / STRUCTURAL),
- load / patch / save of the on-disk fingerprint store.

Change-level semantics (matching the TypeScript ``fingerprint.ts``):

- ``NONE``        — identical content hash; nothing changed.
- ``COSMETIC``    — content changed but the structural signature is identical
  (formatting, comments, internal logic).
- ``STRUCTURAL``  — a function/class signature, import, or export changed, OR
  the file has no structural support (so any change is treated conservatively
  as structural).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .structure import analyze_file

ChangeLevel = Literal["NONE", "COSMETIC", "STRUCTURAL"]


# ---------------------------------------------------------------------------
# Hashing + extraction
# ---------------------------------------------------------------------------


def content_hash(content: str) -> str:
    """SHA-256 hex digest of file content (matches core's ``contentHash``)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def extract_file_fingerprint(file_path: str, content: str, analysis: Any) -> dict:
    """Structural fingerprint from a file's tree-sitter analysis.

    Captures only graph-affecting signatures (function/class/import/export),
    not implementation details. Mirrors core's ``extractFileFingerprint``.
    """
    exported_names = {e.get("name") for e in analysis.exports}

    functions = [
        {
            "name": fn["name"],
            "params": list(fn.get("params", [])),
            "returnType": fn.get("returnType"),
            "exported": fn["name"] in exported_names,
            "lineCount": fn["lineRange"][1] - fn["lineRange"][0] + 1,
        }
        for fn in analysis.functions
    ]

    classes = [
        {
            "name": cls["name"],
            "methods": list(cls.get("methods", [])),
            "properties": list(cls.get("properties", [])),
            "exported": cls["name"] in exported_names,
            "lineCount": cls["lineRange"][1] - cls["lineRange"][0] + 1,
        }
        for cls in analysis.classes
    ]

    imports = [
        {"source": imp["source"], "specifiers": list(imp.get("specifiers", []))}
        for imp in analysis.imports
    ]

    exports = [e["name"] for e in analysis.exports]

    return {
        "filePath": file_path,
        "contentHash": content_hash(content),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "exports": exports,
        "totalLines": len(content.split("\n")),
        "hasStructuralAnalysis": True,
    }


def fingerprint_for_content(file_path: str, content: str) -> dict:
    """Build a single file fingerprint from its content.

    Files without tree-sitter support get a content-hash-only fingerprint
    (``hasStructuralAnalysis: False``): any later change is conservatively
    treated as STRUCTURAL.
    """
    analysis = analyze_file(file_path, content)
    if analysis is not None:
        return extract_file_fingerprint(file_path, content, analysis)
    return {
        "filePath": file_path,
        "contentHash": content_hash(content),
        "functions": [],
        "classes": [],
        "imports": [],
        "exports": [],
        "totalLines": len(content.split("\n")),
        "hasStructuralAnalysis": False,
    }


def fingerprint_for_path(project_dir: Path, rel: str) -> dict | None:
    """Build the fingerprint for a project-relative path. ``None`` if unreadable."""
    abs_path = project_dir / rel
    if not abs_path.exists():
        return None
    try:
        content = abs_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return fingerprint_for_content(rel, content)


def build_fingerprint_store(
    project_dir: Path, file_paths: list[str], git_commit_hash: str
) -> dict:
    """Build a fingerprint store for ``file_paths``.

    Missing/unreadable files are skipped; files without tree-sitter support get
    content-hash-only fingerprints.
    """
    files: dict[str, dict] = {}
    for rel in file_paths:
        fp = fingerprint_for_path(project_dir, rel)
        if fp is not None:
            files[rel] = fp

    return {
        "version": "1.0.0",
        "gitCommitHash": git_commit_hash,
        "generatedAt": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "files": files,
    }


# ---------------------------------------------------------------------------
# Comparison + classification
# ---------------------------------------------------------------------------


def _structural_signature(fp: dict) -> dict:
    """Order-independent structural signature (excludes line counts + hashes)."""
    return {
        "functions": sorted(
            (
                f.get("name", ""),
                tuple(f.get("params", []) or []),
                f.get("returnType"),
                bool(f.get("exported")),
            )
            for f in fp.get("functions", [])
        ),
        "classes": sorted(
            (
                c.get("name", ""),
                tuple(c.get("methods", []) or []),
                tuple(c.get("properties", []) or []),
                bool(c.get("exported")),
            )
            for c in fp.get("classes", [])
        ),
        "imports": sorted(
            (i.get("source", ""), tuple(i.get("specifiers", []) or []))
            for i in fp.get("imports", [])
        ),
        "exports": sorted(fp.get("exports", []) or []),
    }


def _signature_details(old: dict, new: dict) -> list[str]:
    """Human-readable description of the structural differences."""
    details: list[str] = []

    def names(items: list[dict]) -> set[str]:
        return {i.get("name", "") for i in items}

    old_fns, new_fns = names(old.get("functions", [])), names(new.get("functions", []))
    for fn in sorted(new_fns - old_fns):
        details.append(f"new function: {fn}")
    for fn in sorted(old_fns - new_fns):
        details.append(f"removed function: {fn}")

    old_cls, new_cls = names(old.get("classes", [])), names(new.get("classes", []))
    for c in sorted(new_cls - old_cls):
        details.append(f"new class: {c}")
    for c in sorted(old_cls - new_cls):
        details.append(f"removed class: {c}")

    old_exp = set(old.get("exports", []) or [])
    new_exp = set(new.get("exports", []) or [])
    if old_exp != new_exp:
        details.append("exports changed")

    old_imp = {i.get("source", "") for i in old.get("imports", [])}
    new_imp = {i.get("source", "") for i in new.get("imports", [])}
    if old_imp != new_imp:
        details.append("imports changed")

    if not details:
        details.append("signature changed")
    return details


def compare_fingerprints(old: dict, new: dict) -> tuple[ChangeLevel, list[str]]:
    """Classify the change between two fingerprints of the same file."""
    if old.get("contentHash") == new.get("contentHash"):
        return "NONE", []

    if not old.get("hasStructuralAnalysis") or not new.get("hasStructuralAnalysis"):
        return "STRUCTURAL", ["no structural support — treated as structural"]

    if _structural_signature(old) == _structural_signature(new):
        return "COSMETIC", ["internal logic or formatting changed"]

    return "STRUCTURAL", _signature_details(old, new)


def classify_file_change(
    project_dir: Path, rel: str, stored: dict | None
) -> dict:
    """Classify a single changed file relative to its stored fingerprint.

    Returns a ``FileChangeResult``-shaped dict::

        { "filePath", "changeLevel", "status", "details" }

    ``status`` is ``new`` (no stored fingerprint, file on disk),
    ``deleted`` (stored fingerprint, file gone), or ``modified``.
    """
    current = fingerprint_for_path(project_dir, rel)

    if current is None:
        # File is gone (or unreadable): deletion / removal is structural.
        return {
            "filePath": rel,
            "changeLevel": "STRUCTURAL",
            "status": "deleted",
            "details": ["file deleted"],
        }

    if stored is None:
        return {
            "filePath": rel,
            "changeLevel": "STRUCTURAL",
            "status": "new",
            "details": ["new file"],
        }

    level, details = compare_fingerprints(stored, current)
    return {
        "filePath": rel,
        "changeLevel": level,
        "status": "modified",
        "details": details,
    }


# ---------------------------------------------------------------------------
# Update classification (overall decision)
# ---------------------------------------------------------------------------

# Thresholds matching the auto-update prompt's decision gate.
PARTIAL_FILE_LIMIT = 10   # > this many structural files escalates to architecture
FULL_FILE_LIMIT = 30      # > this many structural files recommends a full rebuild
FULL_GRAPH_RATIO = 0.5    # structural files > this fraction of the graph → full


def _dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def classify_update(
    file_changes: list[dict], graph_file_paths: set[str]
) -> dict:
    """Derive the overall ``UpdateDecision`` from per-file classifications.

    - all NONE/COSMETIC → ``SKIP``
    - structural changes within a known set of directories, ≤ limit → ``PARTIAL_UPDATE``
    - new/deleted directories, or > ``PARTIAL_FILE_LIMIT`` structural files →
      ``ARCHITECTURE_UPDATE`` (re-run the architecture analyzer)
    - > ``FULL_FILE_LIMIT`` structural files, or > half the graph → ``FULL_UPDATE``
      (recommend a full rebuild)
    """
    structural = [f for f in file_changes if f.get("changeLevel") == "STRUCTURAL"]
    if not structural:
        return {
            "action": "SKIP",
            "rerunArchitecture": False,
            "reason": "No structural changes detected.",
        }

    count = len(structural)
    total = len(graph_file_paths)

    if count > FULL_FILE_LIMIT or (total > 0 and count > FULL_GRAPH_RATIO * total):
        return {
            "action": "FULL_UPDATE",
            "rerunArchitecture": False,
            "reason": (
                f"{count} files have structural changes — major restructuring; "
                "recommend a full rebuild."
            ),
        }

    known_dirs = {_dir_of(p) for p in graph_file_paths}
    deleted_paths = {f["filePath"] for f in structural if f.get("status") == "deleted"}
    surviving_dirs = {_dir_of(p) for p in (graph_file_paths - deleted_paths)}

    new_dirs = {
        _dir_of(f["filePath"])
        for f in structural
        if f.get("status") == "new" and _dir_of(f["filePath"]) not in known_dirs
    }
    removed_dirs = {
        _dir_of(p)
        for p in deleted_paths
        if _dir_of(p) in known_dirs and _dir_of(p) not in surviving_dirs
    }

    if new_dirs or removed_dirs or count > PARTIAL_FILE_LIMIT:
        if new_dirs or removed_dirs:
            reason = (
                f"{count} structural file(s) span directory-level changes "
                f"({len(new_dirs)} new, {len(removed_dirs)} removed directories) "
                "— re-running architecture."
            )
        else:
            reason = (
                f"{count} structural files exceed the partial limit of "
                f"{PARTIAL_FILE_LIMIT} — re-running architecture."
            )
        return {
            "action": "ARCHITECTURE_UPDATE",
            "rerunArchitecture": True,
            "reason": reason,
        }

    return {
        "action": "PARTIAL_UPDATE",
        "rerunArchitecture": False,
        "reason": f"{count} file(s) have localized structural changes.",
    }


# ---------------------------------------------------------------------------
# Load / patch / save
# ---------------------------------------------------------------------------


def load_fingerprint_store(fp_path: Path) -> tuple[dict, bool]:
    """Load the fingerprint store. Returns ``(store, existed_and_non_empty)``.

    The store is normalized to always carry a ``files`` dict. The boolean flags
    whether the file existed with non-empty content, so :func:`save_fingerprint_store`
    can refuse to clobber a populated store with an empty one (issue #152 guard).
    """
    if not fp_path.exists():
        return {"version": "1.0.0", "files": {}}, False
    raw = fp_path.read_text(encoding="utf-8")
    existed_and_non_empty = raw.strip() != ""
    if not existed_and_non_empty:
        return {"version": "1.0.0", "files": {}}, False
    store = json.loads(raw)
    if not isinstance(store, dict):
        store = {"files": {}}
    store.setdefault("files", {})
    return store, existed_and_non_empty


def patch_fingerprint_store(
    store: dict, project_dir: Path, changed_files: list[str]
) -> dict:
    """LOAD-PATCH-SAVE step: patch (or remove) only the changed files in place.

    For each path: if the file is gone, its entry is removed; otherwise its
    fingerprint is recomputed and replaced. Every other entry is preserved —
    this is the contract that stops a partial update from poisoning the store
    (issue #152). Returns the same ``store`` dict (mutated).
    """
    files = store.setdefault("files", {})
    for rel in changed_files:
        fp = fingerprint_for_path(project_dir, rel)
        if fp is None:
            files.pop(rel, None)
        else:
            files[rel] = fp
    return store


def save_fingerprint_store(
    fp_path: Path, store: dict, existed_and_non_empty: bool, before_count: int
) -> None:
    """Write the store back, guarding against silent-load clobber.

    If the store existed and was non-empty but loaded as zero entries, refuse
    to overwrite — something went wrong reading the file and writing now would
    discard every fingerprint.
    """
    if existed_and_non_empty and before_count == 0:
        raise RuntimeError(
            "fingerprints.json existed and was non-empty but loaded as {} — "
            "refusing to overwrite"
        )
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    fp_path.write_text(
        json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def patch_and_save_fingerprints(
    fp_path: Path,
    project_dir: Path,
    changed_files: list[str],
    git_commit_hash: str | None = None,
) -> tuple[int, int]:
    """Convenience LOAD → PATCH → SAVE wrapper. Returns ``(before, after)`` counts.

    Preserves every unrelated entry; patches/removes only ``changed_files``.
    """
    store, existed = load_fingerprint_store(fp_path)
    before = len(store.get("files", {}))
    patch_fingerprint_store(store, project_dir, changed_files)
    if git_commit_hash is not None:
        store["gitCommitHash"] = git_commit_hash
    after = len(store.get("files", {}))
    save_fingerprint_store(fp_path, store, existed, before)
    return before, after
