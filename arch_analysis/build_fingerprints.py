"""Build the structural-fingerprint baseline for auto-update change detection.

Python port of ``skills/understand/build-fingerprints.mjs`` plus the
``buildFingerprintStore`` / ``extractFileFingerprint`` logic from
``@understand-anything/core``'s ``fingerprint.ts``. Runs once per `/understand`
full rebuild (Phase 7) and writes ``.understand-anything/fingerprints.json``.

Usage:
    python -m arch_analysis.build_fingerprints <input.json>

Input JSON:
    { "projectRoot": str, "sourceFilePaths": [str], "gitCommitHash": str }
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .structure import analyze_file


def content_hash(content: str) -> str:
    """SHA-256 hex digest of file content (matches core's contentHash)."""
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


def build_fingerprint_store(
    project_dir: Path, file_paths: list[str], git_commit_hash: str
) -> dict:
    """Build a fingerprint store for ``file_paths``.

    Files without tree-sitter support get content-hash-only fingerprints
    (conservative: any later change is treated as STRUCTURAL).
    """
    files: dict[str, dict] = {}
    for rel in file_paths:
        abs_path = project_dir / rel
        if not abs_path.exists():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8")
        except OSError:
            continue
        analysis = analyze_file(rel, content)
        if analysis is not None:
            files[rel] = extract_file_fingerprint(rel, content, analysis)
        else:
            files[rel] = {
                "filePath": rel,
                "contentHash": content_hash(content),
                "functions": [],
                "classes": [],
                "imports": [],
                "exports": [],
                "totalLines": len(content.split("\n")),
                "hasStructuralAnalysis": False,
            }

    return {
        "version": "1.0.0",
        "gitCommitHash": git_commit_hash,
        "generatedAt": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write("Usage: python -m arch_analysis.build_fingerprints <input.json>\n")
        return 1

    try:
        payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        sys.stderr.write(f"build_fingerprints failed: cannot read {args[0]}: {err}\n")
        return 1

    project_root = payload.get("projectRoot")
    source_file_paths = payload.get("sourceFilePaths")
    git_commit_hash = payload.get("gitCommitHash")
    if (
        not project_root
        or not isinstance(source_file_paths, list)
        or not isinstance(git_commit_hash, str)
    ):
        sys.stderr.write(
            "Invalid input: requires { projectRoot: str, sourceFilePaths: [str], "
            "gitCommitHash: str }\n"
        )
        return 1

    project_dir = Path(project_root)
    store = build_fingerprint_store(project_dir, source_file_paths, git_commit_hash)

    out_dir = project_dir / ".understand-anything"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "fingerprints.json"
    out_path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")

    sys.stdout.write(f"Fingerprints baseline: {len(store['files'])} files\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
