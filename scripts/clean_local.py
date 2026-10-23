#!/usr/bin/env python3
"""Remove known local installation/cache paths, preserving generated indexes.

Only the selected repository is inspected; global host installations are untouched.
All removals use rm, after checking ownership, symlink parents and tracked files.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

SOURCE = Path(__file__).resolve().parents[1]
PLUGIN = SOURCE / "understand-anything-plugin"
SKILL_DIRS = (
    ".agents/skills", ".claude/skills", ".github/skills", ".junie/skills",
    ".kilo/skills", ".kiro/skills", ".cursor/skills",
)
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache"}


def project_data_dir(root):
    current = root / ".ua"
    legacy = root / ".understand-anything"
    return current if current.is_dir() or not legacy.is_dir() else legacy


def owned_payload(path):
    try:
        return json.loads((path / ".claude-plugin/plugin.json").read_text()).get("name") == "understand-anything"
    except (OSError, ValueError, AttributeError):
        return False


def safe_parent(path, root):
    """Never traverse a repository's directory symlinks to remove external files."""
    return all(not parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents)


def installed_paths(root):
    payload = root / ".agents/understand-anything-plugin"
    roots = [PLUGIN.resolve()]
    if safe_parent(payload, root) and owned_payload(payload):
        roots.append(payload.resolve())
    for rel in SKILL_DIRS:
        directory = root / rel
        if not safe_parent(directory / "placeholder", root) or not directory.is_dir():
            continue
        for link in directory.iterdir():
            if not link.is_symlink():
                continue
            target = link.resolve()
            # Compare exact skill destinations, including dangling links left by
            # an earlier payload removal; never match arbitrary relative links.
            expected = [base / "skills" / link.name for base in roots]
            expected.append(payload / "skills" / link.name)
            if target in expected and link.name.startswith("understand"):
                yield link
    tools = project_data_dir(root) / "tools"
    if safe_parent(tools / "placeholder", root) and tools.is_dir():
        for path in tools.iterdir():
            if path.is_file() and not path.is_symlink() and "# Understand-Anything tool wrapper" in path.read_text(errors="replace"):
                yield path
    workflows = root / ".kilocode/workflows"
    if safe_parent(workflows / "placeholder", root) and workflows.is_dir():
        for path in workflows.glob("understand-*.md"):
            if path.is_file() and not path.is_symlink():
                text = path.read_text(errors="replace")
                if "tools/commands/" in text and "understand-anything" in text.lower():
                    yield path
    if payload.resolve() != PLUGIN.resolve() and safe_parent(payload, root) and owned_payload(payload):
        yield payload


def cache_paths(root):
    # Preserve the graph, parts, metadata, fingerprints, embeddings, config and
    # any future index files. Only known scratch/cache names are removed here.
    artifacts = project_data_dir(root)
    intermediate = artifacts / "intermediate"
    if safe_parent(intermediate / "placeholder", root) and intermediate.is_dir():
        for path in intermediate.iterdir():
            if path.name not in {"scan-result.json", "save-summary.json"}:
                yield path
    for name in ("tmp", "cache", ".cache"):
        yield artifacts / name
    if safe_parent(artifacts / "placeholder", root) and artifacts.is_dir():
        yield from artifacts.glob(".trash-*")
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in list(dirs):
            path = base / name
            if name in CACHE_DIRS:
                yield path
                dirs.remove(name)
            elif name in {".git", ".ua", ".understand-anything", "node_modules", "target", "dist", "build", ".venv", "venv"} or path.is_symlink():
                dirs.remove(name)
        for name in files:
            if name.endswith((".pyc", ".pyo", ".tsbuildinfo")):
                yield base / name


def tracked_paths(root):
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--full-name", "-z"],
        capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError(f"not a Git repository: {root}")
    top = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(top).resolve() != root:
        raise ValueError(f"select the repository root, not a subdirectory: {root}")
    return [root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "skills", "cache", "build", "stamps"), required=True)
    parser.add_argument("--repo", type=Path, default=Path(os.environ.get("LOCAL") or "."))
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("DRY_RUN") == "1")
    args = parser.parse_args()
    root = SOURCE if args.mode in {"build", "stamps"} else args.repo.resolve()
    try:
        tracked = tracked_paths(root)
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    candidates = []
    if args.mode in {"local", "skills"}:
        candidates.extend(installed_paths(root))
    if args.mode in {"local", "cache"}:
        candidates.extend(cache_paths(root))
    if args.mode == "build":
        candidates.extend(root / rel for rel in (
            "understand-anything-plugin/packages/rust/target",
            "understand-anything-plugin/packages/dashboard/node_modules",
            "understand-anything-plugin/packages/dashboard/dist", "build", "dist",
        ))
    if args.mode == "stamps":
        candidates.append(root / "build/.make")
    for path in dict.fromkeys(candidates):
        if not (path.exists() or path.is_symlink()):
            continue
        if not safe_parent(path, root):
            print(f"Keep (symlink parent): {path}")
            continue
        if any(item == path or path in item.parents for item in tracked):
            print(f"Keep (contains tracked files): {path}")
            continue
        print(f"{'Would remove' if args.dry_run else 'Remove'}: {path}", flush=True)
        if not args.dry_run:
            subprocess.run(["rm", "-rf", "--", str(path)], check=True)


if __name__ == "__main__":
    main()
