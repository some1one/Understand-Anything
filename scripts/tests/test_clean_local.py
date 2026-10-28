"""Cleanup ownership and preservation checks using isolated repositories."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "clean_local.py"


def write(path, text="keep"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def run(root, *args):
    env = dict(os.environ, DRY_RUN="")
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(root), *args],
                          capture_output=True, text=True, check=True, env=env)


def test_cleanup_preserves_indexes_unrelated_skills_and_tracked_files(tmp_path):
    root = tmp_path / "repo with spaces"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    payload = root / ".agents/understand-anything-plugin"
    write(payload / ".claude-plugin/plugin.json", json.dumps({"name": "understand-anything"}))
    write(payload / "skills/understand/SKILL.md")
    links = root / ".agents/skills"
    links.mkdir()
    own = links / "understand"
    own.symlink_to("../understand-anything-plugin/skills/understand")
    unrelated = write(links / "user-skill/SKILL.md")
    foreign = links / "understand-other"
    foreign.symlink_to(tmp_path / "unrelated/skills/understand-other")
    graph = write(root / ".understand-anything/knowledge-graph.json")
    part = write(root / ".understand-anything/parts/src/knowledge-graph.json")
    fingerprints = write(root / ".understand-anything/fingerprints.json")
    scan = write(root / ".understand-anything/intermediate/scan-result.json")
    scratch = write(root / ".understand-anything/intermediate/batch-1.json")
    cache = write(root / "scripts/__pycache__/module.pyc")
    tracked = write(root / ".cache/tracked.txt")
    subprocess.run(["git", "-C", str(root), "add", ".cache/tracked.txt"], check=True)
    wrapper = write(root / ".understand-anything/tools/validate", "# Understand-Anything tool wrapper (validate)")
    custom_tool = write(root / ".understand-anything/tools/custom")
    run(root, "--mode", "local", "--dry-run")
    assert own.is_symlink() and payload.exists() and cache.exists()
    run(root, "--mode", "local")
    assert not own.is_symlink() and not payload.exists()
    assert not scratch.exists() and not cache.exists() and not wrapper.exists()
    assert foreign.is_symlink()
    assert all(path.read_text() == "keep" for path in (unrelated, graph, part, fingerprints, scan, tracked, custom_tool))
    run(root, "--mode", "local")  # Repeated cleanup is safe.


def test_cleanup_does_not_follow_directory_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    external = tmp_path / "external"
    cached = write(external / "tmp/cache.txt")
    payload = external / "understand-anything-plugin"
    write(payload / ".claude-plugin/plugin.json", json.dumps({"name": "understand-anything"}))
    (root / ".understand-anything").symlink_to(external, target_is_directory=True)
    (root / ".agents").symlink_to(external, target_is_directory=True)
    run(root, "--mode", "local")
    assert cached.exists() and payload.exists()


@pytest.mark.parametrize("target,expected", [
    ("install", ["codex", "--local"]),
    ("install-local", ["codex", "--local"]),
    ("install-codex", ["codex", "--local"]),
    ("uninstall-codex", ["--uninstall", "codex", "--local"]),
    ("install-junie", ["junie", "--local"]),
    ("install-jetbrains", ["jetbrains", "--local"]),
    ("uninstall-junie", ["--uninstall", "junie", "--local"]),
    ("uninstall-jetbrains", ["--uninstall", "jetbrains", "--local"]),
])
def test_make_install_paths_are_literal_and_keep_spaces(tmp_path, target, expected):
    repo = tmp_path / "checkout"
    repo.mkdir()
    write(repo / "Makefile", (SCRIPT.parents[1] / "Makefile").read_text())
    installer = write(repo / "install.sh", '#!/bin/sh\nprintf "%s\\n" "$@"\n')
    installer.chmod(0o755)
    local = str(tmp_path / "repo with spaces $(touch should-not-exist) `touch also-not-created`")
    result = subprocess.run(["make", "--no-print-directory", "-o", "build", target, f"LOCAL={local}"],
                            cwd=repo, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [*expected, local]
    assert not (repo / "should-not-exist").exists()
    assert not (repo / "also-not-created").exists()
