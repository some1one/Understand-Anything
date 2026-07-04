"""Build the structural-fingerprint baseline for auto-update change detection.

Python port of ``skills/understand/build-fingerprints.mjs`` plus the
``buildFingerprintStore`` / ``extractFileFingerprint`` logic from
``@understand-anything/core``'s ``fingerprint.ts``. Runs once per `/understand`
full rebuild (Phase 7) and writes ``.understand-anything/fingerprints.json``.

The fingerprint logic itself lives in :mod:`arch_analysis.fingerprints` (shared
with the ``auto_update_*`` commands); this module is the baseline CLI wrapper.

Usage:
    python -m arch_analysis.build_fingerprints <input.json>

Input JSON:
    { "projectRoot": str, "sourceFilePaths": [str], "gitCommitHash": str }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Re-exported for backwards compatibility with existing imports/tests.
from .fingerprints import (
    build_fingerprint_store,
    content_hash,
    extract_file_fingerprint,
)

__all__ = [
    "build_fingerprint_store",
    "content_hash",
    "extract_file_fingerprint",
    "main",
]


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
