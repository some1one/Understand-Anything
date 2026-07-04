"""Generate the architecture-analyzer input JSON for a whole project.

Walks a project directory, enumerates its files (obeying ``.gitignore`` by
default), infers a node type for each, and writes the ``{fileNodes,
importEdges, allEdges}`` payload that :mod:`arch_analysis.analyze` consumes.

This produces the *file inventory* only. ``importEdges`` and ``allEdges`` are
emitted as empty arrays — the analysis pipeline supplies edges (from tree-sitter
import resolution) by merging them into this file before running the analyzer.

Usage::

    python -m arch_analysis.generate_input <project_root> <output.json> \\
        [--include GLOB ...] [--exclude GLOB ...] [--no-gitignore]

``.gitignore`` is honoured by default: inside a git repo via ``git ls-files``
(which respects nested ``.gitignore``, global excludes and ``.git/info/exclude``),
otherwise via the repo-root ``.gitignore`` parsed with ``pathspec``. Pass
``--no-gitignore`` to enumerate every file (the ``.git`` directory is always
skipped).

Exit 0 on success, exit 1 on fatal error (message printed to stderr).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import orjson
import pathspec

from .patterns import infer_node_type


def _git_tracked_and_untracked(root: Path) -> list[str] | None:
    """List non-ignored files via git, or ``None`` if not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk(root: Path) -> list[str]:
    """Recursively list every file path (relative, posix), skipping ``.git``."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root)
            out.append(rel.as_posix())
    return out


def _gitignore_spec(root: Path) -> pathspec.PathSpec | None:
    """Compile the repo-root ``.gitignore`` into a pathspec, if present."""
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return None
    return pathspec.PathSpec.from_lines(
        "gitignore", gitignore.read_text(encoding="utf-8").splitlines()
    )


def list_project_files(root: Path, respect_gitignore: bool = True) -> list[str]:
    """Enumerate project files as relative posix paths."""
    if respect_gitignore:
        tracked = _git_tracked_and_untracked(root)
        if tracked is not None:
            return tracked
        # Not a git repo: fall back to a walk filtered by root .gitignore.
        spec = _gitignore_spec(root)
        files = _walk(root)
        if spec is not None:
            files = [f for f in files if not spec.match_file(f)]
        return files
    return _walk(root)


def _filter(
    files: list[str], include: list[str], exclude: list[str]
) -> list[str]:
    """Apply gitignore-style ``--include`` whitelist and ``--exclude`` globs."""
    inc = pathspec.PathSpec.from_lines("gitignore", include) if include else None
    exc = pathspec.PathSpec.from_lines("gitignore", exclude) if exclude else None
    out = []
    for f in files:
        if inc is not None and not inc.match_file(f):
            continue
        if exc is not None and exc.match_file(f):
            continue
        out.append(f)
    return out


def build_file_nodes(files: list[str]) -> list[dict]:
    """Build ``fileNodes`` entries (id, type, name, filePath) from paths."""
    nodes = []
    for rel in sorted(files):
        ntype = infer_node_type(rel)
        nodes.append(
            {
                "id": f"{ntype}:{rel}",
                "type": ntype,
                "name": rel.rsplit("/", 1)[-1],
                "filePath": rel,
                "summary": "",
                "tags": [],
            }
        )
    return nodes


def generate(
    root: Path,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    respect_gitignore: bool = True,
) -> dict:
    """Produce the full input payload for a project directory."""
    files = list_project_files(root, respect_gitignore=respect_gitignore)
    files = _filter(files, include or [], exclude or [])
    return {
        "fileNodes": build_file_nodes(files),
        "importEdges": [],
        "allEdges": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arch_analysis.generate_input",
        description="Generate the architecture-analyzer input JSON for a project.",
    )
    parser.add_argument("project_root", type=Path, help="project directory to scan")
    parser.add_argument("output", type=Path, help="path to write the input JSON")
    parser.add_argument(
        "--include",
        nargs="+",
        default=[],
        metavar="GLOB",
        help="whitelist: keep only files matching these gitignore-style globs",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        metavar="GLOB",
        help="drop files matching these gitignore-style globs",
    )
    parser.add_argument(
        "--no-gitignore",
        action="store_true",
        help="do not obey .gitignore (still skips the .git directory)",
    )
    args = parser.parse_args(argv)

    try:
        root = args.project_root.resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"not a directory: {root}")
        payload = generate(
            root,
            include=args.include,
            exclude=args.exclude,
            respect_gitignore=not args.no_gitignore,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    except Exception as exc:  # noqa: BLE001 -- surface any failure to stderr
        print(f"arch_analysis.generate_input: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {len(payload['fileNodes'])} file nodes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
