"""Structural fingerprinting — port of ``packages/core/src/fingerprint.ts``.

Reuses :func:`arch_analysis.fingerprints.content_hash` for the SHA-256 hash
(the signatures match exactly). The fingerprint *extraction* and *comparison*
detail strings are ported from the TS source verbatim, because the dashboard
tests assert the TS wording (``new function: x``, ``params changed: x``,
``internal logic changed (no structural impact)``), which differs from
arch_analysis's terser ``signature changed`` wording.

Fingerprints are plain dicts with camelCase keys (matching the on-disk
``fingerprints.json`` wire format), not pydantic models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

# Reuse the content hash from arch_analysis (identical SHA-256 hex digest).
from arch_analysis.fingerprints import content_hash

ChangeLevel = Literal["NONE", "COSMETIC", "STRUCTURAL"]


# ---------------------------------------------------------------------------
# Fingerprint TypedDicts (wire shapes)
# ---------------------------------------------------------------------------


class FunctionFingerprint(TypedDict, total=False):
    name: str
    params: list[str]
    returnType: str | None
    exported: bool
    lineCount: int


class ClassFingerprint(TypedDict, total=False):
    name: str
    methods: list[str]
    properties: list[str]
    exported: bool
    lineCount: int


class ImportFingerprint(TypedDict):
    source: str
    specifiers: list[str]


class FileFingerprint(TypedDict, total=False):
    filePath: str
    contentHash: str
    functions: list[FunctionFingerprint]
    classes: list[ClassFingerprint]
    imports: list[ImportFingerprint]
    exports: list[str]
    totalLines: int
    hasStructuralAnalysis: bool


class FingerprintStore(TypedDict, total=False):
    version: str
    gitCommitHash: str
    generatedAt: str
    files: dict[str, FileFingerprint]


class FileChangeResult(TypedDict):
    filePath: str
    changeLevel: ChangeLevel
    details: list[str]


class ChangeAnalysis(TypedDict):
    fileChanges: list[FileChangeResult]
    newFiles: list[str]
    deletedFiles: list[str]
    structurallyChangedFiles: list[str]
    cosmeticOnlyFiles: list[str]
    unchangedFiles: list[str]


class PluginRegistry(Protocol):
    """Minimal protocol matching core's ``PluginRegistry.analyzeFile``."""

    def analyze_file(self, file_path: str, content: str) -> Any | None: ...


# ---------------------------------------------------------------------------
# Helpers for reading analysis (which may be a dict or a pydantic-style object)
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def extract_file_fingerprint(
    file_path: str, content: str, analysis: Any
) -> FileFingerprint:
    """Extract a structural fingerprint from a file's tree-sitter analysis.

    Captures only graph-affecting signatures (function/class/import/export),
    not implementation details.
    """
    exports_raw = _get(analysis, "exports", []) or []
    exported_names = {_get(e, "name") for e in exports_raw}

    functions: list[FunctionFingerprint] = []
    for fn in _get(analysis, "functions", []) or []:
        line_range = _get(fn, "lineRange")
        functions.append({
            "name": _get(fn, "name"),
            "params": list(_get(fn, "params", []) or []),
            "returnType": _get(fn, "returnType"),
            "exported": _get(fn, "name") in exported_names,
            "lineCount": line_range[1] - line_range[0] + 1,
        })

    classes: list[ClassFingerprint] = []
    for cls in _get(analysis, "classes", []) or []:
        line_range = _get(cls, "lineRange")
        classes.append({
            "name": _get(cls, "name"),
            "methods": list(_get(cls, "methods", []) or []),
            "properties": list(_get(cls, "properties", []) or []),
            "exported": _get(cls, "name") in exported_names,
            "lineCount": line_range[1] - line_range[0] + 1,
        })

    imports: list[ImportFingerprint] = [
        {"source": _get(imp, "source"), "specifiers": list(_get(imp, "specifiers", []) or [])}
        for imp in _get(analysis, "imports", []) or []
    ]

    exports = [_get(e, "name") for e in exports_raw]

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


def _content_only_fingerprint(file_path: str, content: str) -> FileFingerprint:
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


def compare_fingerprints(
    old_fp: FileFingerprint, new_fp: FileFingerprint
) -> FileChangeResult:
    """Compare two file fingerprints and determine the change level."""
    details: list[str] = []

    # Fast path: identical content
    if old_fp.get("contentHash") == new_fp.get("contentHash"):
        return {"filePath": new_fp["filePath"], "changeLevel": "NONE", "details": []}

    # Conservative: missing structural analysis → STRUCTURAL
    if not old_fp.get("hasStructuralAnalysis") or not new_fp.get("hasStructuralAnalysis"):
        return {
            "filePath": new_fp["filePath"],
            "changeLevel": "STRUCTURAL",
            "details": ["no structural analysis available — conservative classification"],
        }

    old_fns = old_fp.get("functions", []) or []
    new_fns = new_fp.get("functions", []) or []
    old_func_names = {f["name"] for f in old_fns}
    new_func_names = {f["name"] for f in new_fns}

    for name in new_func_names:
        if name not in old_func_names:
            details.append(f"new function: {name}")
    for name in old_func_names:
        if name not in new_func_names:
            details.append(f"removed function: {name}")

    for new_fn in new_fns:
        old_fn = next((f for f in old_fns if f["name"] == new_fn["name"]), None)
        if old_fn is None:
            continue
        if list(old_fn.get("params", [])) != list(new_fn.get("params", [])):
            details.append(f"params changed: {new_fn['name']}")
        if old_fn.get("returnType") != new_fn.get("returnType"):
            details.append(f"return type changed: {new_fn['name']}")
        if old_fn.get("exported") != new_fn.get("exported"):
            details.append(f"export status changed: {new_fn['name']}")
        old_lc = old_fn.get("lineCount", 0)
        new_lc = new_fn.get("lineCount", 0)
        if old_lc > 0:
            ratio = new_lc / old_lc
            if ratio > 1.5 or ratio < 0.5:
                details.append(
                    f"significant size change: {new_fn['name']} "
                    f"({old_lc} → {new_lc} lines)"
                )

    old_classes = old_fp.get("classes", []) or []
    new_classes = new_fp.get("classes", []) or []
    old_class_names = {c["name"] for c in old_classes}
    new_class_names = {c["name"] for c in new_classes}

    for name in new_class_names:
        if name not in old_class_names:
            details.append(f"new class: {name}")
    for name in old_class_names:
        if name not in new_class_names:
            details.append(f"removed class: {name}")

    for new_cls in new_classes:
        old_cls = next((c for c in old_classes if c["name"] == new_cls["name"]), None)
        if old_cls is None:
            continue
        if sorted(old_cls.get("methods", [])) != sorted(new_cls.get("methods", [])):
            details.append(f"methods changed: {new_cls['name']}")
        if sorted(old_cls.get("properties", [])) != sorted(new_cls.get("properties", [])):
            details.append(f"properties changed: {new_cls['name']}")
        if old_cls.get("exported") != new_cls.get("exported"):
            details.append(f"export status changed: {new_cls['name']}")

    old_imports = sorted(
        f"{i['source']}:{','.join(sorted(i.get('specifiers', [])))}"
        for i in (old_fp.get("imports", []) or [])
    )
    new_imports = sorted(
        f"{i['source']}:{','.join(sorted(i.get('specifiers', [])))}"
        for i in (new_fp.get("imports", []) or [])
    )
    if old_imports != new_imports:
        details.append("imports changed")

    old_exports = sorted(old_fp.get("exports", []) or [])
    new_exports = sorted(new_fp.get("exports", []) or [])
    if old_exports != new_exports:
        details.append("exports changed")

    if details:
        return {"filePath": new_fp["filePath"], "changeLevel": "STRUCTURAL", "details": details}

    # Content changed but structure is identical
    return {
        "filePath": new_fp["filePath"],
        "changeLevel": "COSMETIC",
        "details": ["internal logic changed (no structural impact)"],
    }


def build_fingerprint_store(
    project_dir: str | Path,
    file_paths: list[str],
    registry: PluginRegistry,
    git_commit_hash: str,
) -> FingerprintStore:
    """Build a fingerprint store for a set of files."""
    root = Path(project_dir)
    files: dict[str, FileFingerprint] = {}

    for rel in file_paths:
        abs_path = root / rel
        if not abs_path.exists():
            continue
        content = abs_path.read_text(encoding="utf-8")
        analysis = registry.analyze_file(rel, content)
        if analysis is not None:
            files[rel] = extract_file_fingerprint(rel, content, analysis)
        else:
            files[rel] = _content_only_fingerprint(rel, content)

    return {
        "version": "1.0.0",
        "gitCommitHash": git_commit_hash,
        "generatedAt": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "files": files,
    }


def analyze_changes(
    project_dir: str | Path,
    changed_files: list[str],
    existing_store: FingerprintStore,
    registry: PluginRegistry,
) -> ChangeAnalysis:
    """Analyze changes between current files and stored fingerprints."""
    root = Path(project_dir)
    file_changes: list[FileChangeResult] = []
    new_files: list[str] = []
    deleted_files: list[str] = []
    structurally_changed: list[str] = []
    cosmetic_only: list[str] = []
    unchanged: list[str] = []

    store_files = existing_store.get("files", {})

    for rel in changed_files:
        abs_path = root / rel
        existed_before = rel in store_files
        exists_now = abs_path.exists()

        if not exists_now:
            if existed_before:
                deleted_files.append(rel)
                file_changes.append({
                    "filePath": rel,
                    "changeLevel": "STRUCTURAL",
                    "details": ["file deleted"],
                })
            continue

        if not existed_before:
            new_files.append(rel)
            file_changes.append({
                "filePath": rel,
                "changeLevel": "STRUCTURAL",
                "details": ["new file"],
            })
            continue

        content = abs_path.read_text(encoding="utf-8")
        analysis = registry.analyze_file(rel, content)
        old_fp = store_files[rel]

        if analysis is not None:
            new_fp = extract_file_fingerprint(rel, content, analysis)
        else:
            new_fp = _content_only_fingerprint(rel, content)

        result = compare_fingerprints(old_fp, new_fp)
        file_changes.append(result)

        level = result["changeLevel"]
        if level == "NONE":
            unchanged.append(rel)
        elif level == "COSMETIC":
            cosmetic_only.append(rel)
        else:
            structurally_changed.append(rel)

    return {
        "fileChanges": file_changes,
        "newFiles": new_files,
        "deletedFiles": deleted_files,
        "structurallyChangedFiles": structurally_changed,
        "cosmeticOnlyFiles": cosmetic_only,
        "unchangedFiles": unchanged,
    }


__all__ = [
    "ChangeLevel",
    "FunctionFingerprint",
    "ClassFingerprint",
    "ImportFingerprint",
    "FileFingerprint",
    "FingerprintStore",
    "FileChangeResult",
    "ChangeAnalysis",
    "PluginRegistry",
    "content_hash",
    "extract_file_fingerprint",
    "compare_fingerprints",
    "build_fingerprint_store",
    "analyze_changes",
]
