"""Shared helpers for the deterministic ``auto_update_*`` command modules.

Centralizes the ``.understand-anything`` path layout, JSON IO, git plumbing,
source-file filtering, and ``meta.json`` writes so each phase module stays
focused on its own logic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UA_DIRNAME = ".understand-anything"
INTERMEDIATE_DIRNAME = "intermediate"

# Source-file extensions the auto-update pipeline tracks (matches the hook's
# documented filter). Non-source changes only bump metadata; they never trigger
# LLM re-analysis.
SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
        ".py", ".go", ".rs", ".java", ".rb",
        ".cpp", ".cc", ".c", ".h", ".hpp",
        ".cs", ".swift", ".kt", ".php",
    }
)

META_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Path layout
# ---------------------------------------------------------------------------


def ua_dir(project_root: Path) -> Path:
    return project_root / UA_DIRNAME


def intermediate_dir(project_root: Path) -> Path:
    return ua_dir(project_root) / INTERMEDIATE_DIRNAME


def graph_path(project_root: Path) -> Path:
    return ua_dir(project_root) / "knowledge-graph.json"


def meta_path(project_root: Path) -> Path:
    return ua_dir(project_root) / "meta.json"


def fingerprints_path(project_root: Path) -> Path:
    return ua_dir(project_root) / "fingerprints.json"


def scan_result_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "scan-result.json"


def state_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "auto-update-state.json"


def change_analysis_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "change-analysis.json"


def batches_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "batches.json"


def dispatch_summary_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "dispatch-summary.json"


def merged_graph_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "merged-graph.json"


def arch_input_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "ua-arch-input.json"


def layers_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "layers.json"


def summary_path(project_root: Path) -> Path:
    return intermediate_dir(project_root) / "auto-update-summary.json"


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------


def read_json(path: Path) -> Any | None:
    """Load JSON, returning ``None`` if the file is missing or unparseable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def emit(data: Any) -> None:
    """Print a machine-readable JSON payload to stdout (one object)."""
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Source filtering
# ---------------------------------------------------------------------------


def is_source_file(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    if "." not in base:
        return False
    return ("." + base.rsplit(".", 1)[-1].lower()) in SOURCE_EXTENSIONS


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------


def git_head(project_root: Path) -> str | None:
    """Current ``HEAD`` commit hash, or ``None`` if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def git_changed_files(project_root: Path, prev: str, head: str) -> list[str] | None:
    """``git diff <prev>..<head> --name-only`` as a list of relative paths.

    ``None`` if the diff command fails (e.g. the stored commit is unknown).
    """
    try:
        result = subprocess.run(
            ["git", "diff", f"{prev}..{head}", "--name-only"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# meta.json
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def graph_file_paths(graph: Any) -> set[str]:
    """The set of project-relative file paths referenced by a graph's nodes."""
    from .validate_graph import _node_file_path

    if not isinstance(graph, dict):
        return set()
    out: set[str] = set()
    for n in graph.get("nodes", []) or []:
        if isinstance(n, dict):
            p = _node_file_path(n)
            if p:
                out.add(p)
    return out


def write_meta(
    project_root: Path, commit_hash: str, analyzed_files: int | None = None
) -> None:
    """Patch ``meta.json`` with a new commit hash + timestamp, preserving fields."""
    path = meta_path(project_root)
    meta = read_json(path)
    if not isinstance(meta, dict):
        meta = {}
    meta["lastAnalyzedAt"] = _now_iso()
    meta["gitCommitHash"] = commit_hash
    meta.setdefault("version", META_VERSION)
    if analyzed_files is not None:
        meta["analyzedFiles"] = analyzed_files
    write_json(path, meta)
