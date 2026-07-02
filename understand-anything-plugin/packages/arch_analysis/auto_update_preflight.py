"""Auto-update Phase 0 — pre-flight (zero token cost).

Validates the existing graph + metadata, reads the stored commit hash, collects
changed files from git, filters to source files, applies ``.understandignore``,
creates the intermediate directory, and writes ``auto-update-state.json``.

Metadata-only stop cases (no graph/meta, up-to-date, no changes, no source
changes, all-ignored) are handled here: the state's ``status`` becomes
``STOP`` and ``meta.json`` is bumped to the current commit where appropriate.

Usage:
    python -m arch_analysis.auto_update_preflight <project-root> [--force]

The resulting state is both written to ``intermediate/auto-update-state.json``
(when ``.understand-anything`` exists) and printed as JSON to stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import auto_update_common as c
from .languages import create_ignore_filter


def run(project_root: Path, force: bool = False) -> dict:
    """Run pre-flight and return the ``AutoUpdateState`` dict."""

    def state(
        status: str,
        action: str,
        reason: str,
        *,
        previous: str | None = None,
        current: str | None = None,
        changed: list[str] | None = None,
        metadata_updated: bool = False,
    ) -> dict:
        return {
            "status": status,
            "action": action,
            "reason": reason,
            "projectRoot": str(project_root),
            "previousCommit": previous,
            "currentCommit": current,
            "changedSourceFiles": changed or [],
            "metadataUpdated": metadata_updated,
        }

    # 1–2. Graph + metadata must exist.
    if not c.graph_path(project_root).exists():
        return state(
            "STOP",
            "NO_GRAPH",
            "No existing knowledge graph found. Run `/understand` first to create one.",
        )

    meta = c.read_json(c.meta_path(project_root))
    if not isinstance(meta, dict) or not meta.get("gitCommitHash"):
        return state(
            "STOP",
            "NO_META",
            "No analysis metadata found. Run `/understand` to create a baseline.",
        )

    previous = meta["gitCommitHash"]

    # 3. Current commit.
    current = c.git_head(project_root)
    if current is None:
        return state(
            "STOP",
            "NO_META",
            "Not a git repository or cannot read HEAD; auto-update aborted.",
            previous=previous,
        )

    # 4. Up to date.
    if current == previous and not force:
        return state(
            "STOP",
            "UP_TO_DATE",
            "Knowledge graph is already up to date.",
            previous=previous,
            current=current,
        )

    # 5. Changed files.
    changed = c.git_changed_files(project_root, previous, current)
    if changed is None:
        # Diff failed (unknown stored commit etc.) — be conservative and stop
        # without touching metadata so a manual re-baseline is obvious.
        return state(
            "STOP",
            "NO_META",
            f"Cannot diff {previous}..{current}; stored baseline commit may be "
            "unknown. Run `/understand` to re-baseline.",
            previous=previous,
            current=current,
        )

    if not changed:
        c.write_meta(project_root, current)
        return state(
            "STOP",
            "NO_CHANGES",
            "No files changed between commits. Metadata updated.",
            previous=previous,
            current=current,
            metadata_updated=True,
        )

    # 6. Source files only.
    source_files = [p for p in changed if c.is_source_file(p)]
    if not source_files:
        c.write_meta(project_root, current)
        return state(
            "STOP",
            "NO_SOURCE_CHANGES",
            "Only non-source files changed. Metadata updated.",
            previous=previous,
            current=current,
            metadata_updated=True,
        )

    # 7. Apply .understandignore exclusions.
    ignore_filter = create_ignore_filter(project_root)
    kept = [p for p in source_files if not ignore_filter.is_ignored(p)]
    if not kept:
        c.write_meta(project_root, current)
        return state(
            "STOP",
            "ALL_IGNORED",
            "All changed source files are in ignored paths. Metadata updated.",
            previous=previous,
            current=current,
            metadata_updated=True,
        )

    # 8. Proceed: ensure intermediate dir exists.
    c.intermediate_dir(project_root).mkdir(parents=True, exist_ok=True)

    return state(
        "CONTINUE",
        "PROCEED",
        f"{len(kept)} changed source file(s) to inspect.",
        previous=previous,
        current=current,
        changed=sorted(kept),
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    positional = [a for a in args if not a.startswith("-")]
    force = "--force" in args

    if not positional:
        sys.stderr.write(
            "Usage: python -m arch_analysis.auto_update_preflight <project-root> [--force]\n"
        )
        return 1

    project_root = Path(positional[0]).resolve()
    result = run(project_root, force=force)

    # Persist the state file whenever .understand-anything exists.
    if c.ua_dir(project_root).exists():
        c.intermediate_dir(project_root).mkdir(parents=True, exist_ok=True)
        c.write_json(c.state_path(project_root), result)

    c.emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
