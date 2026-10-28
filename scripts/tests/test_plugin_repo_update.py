"""Session hooks pull only an explicit plugin checkout, using local Git remotes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "understand-anything-plugin"
HOOK = PLUGIN / "hooks/auto_update.py"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def identity(root):
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repositories(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True)
    identity(seed)
    for rel, value in {
        "understand-anything-plugin/.claude-plugin/plugin.json": {"name": "understand-anything"},
        "understand-anything-plugin/.claude-plugin/marketplace.json": {"name": "understand-anything", "plugins": []},
    }.items():
        path = seed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    (seed / "source.txt").write_text("original\n")
    baseline = commit(seed)
    git(seed, "push", "-qu", "origin", "main")
    plugin = tmp_path / "plugin repo with spaces"
    subprocess.run(["git", "clone", "-q", str(remote), str(plugin)], check=True)
    identity(plugin)
    project = tmp_path / "analyzed project"
    subprocess.run(["git", "clone", "-q", str(remote), str(project)], check=True)
    (seed / "source.txt").write_text("remote update\n")
    latest = commit(seed)
    git(seed, "push", "-q")
    return plugin, project, baseline, latest


def hook(plugin, project, event="SessionStart"):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"hook_event_name": event, "tool_name": "Bash", "cwd": str(project)}),
        text=True, capture_output=True, check=True,
        env={**os.environ, "UA_PLUGIN_REPO": str(plugin)},
    )
    return json.loads(result.stdout) if result.stdout else None


def test_session_start_pulls_plugin_without_touching_analyzed_repository(repositories):
    plugin, project, baseline, latest = repositories
    result = hook(plugin, project)
    assert "updated" in result["hookSpecificOutput"]["additionalContext"]
    assert "updated" in result["systemMessage"]
    assert git(plugin, "rev-parse", "HEAD") == latest
    assert git(project, "rev-parse", "HEAD") == baseline
    assert (project / "source.txt").read_text() == "original\n"
    assert hook(plugin, project) is None  # Up-to-date pulls need no extra context.


@pytest.mark.parametrize("dirty", ["untracked", "staged", "unstaged"])
def test_dirty_plugin_is_not_pulled_or_stashed(repositories, dirty):
    plugin, project, baseline, _ = repositories
    path = plugin / ("new.txt" if dirty == "untracked" else "source.txt")
    path.write_text("local work\n")
    if dirty == "staged":
        git(plugin, "add", "source.txt")
    before = git(plugin, "status", "--porcelain")
    result = hook(plugin, project)
    assert "local changes" in result["hookSpecificOutput"]["additionalContext"]
    assert git(plugin, "rev-parse", "HEAD") == baseline
    assert git(plugin, "status", "--porcelain") == before
    assert path.read_text() == "local work\n"
    assert not git(plugin, "stash", "list")


def test_diverged_plugin_fails_without_rebase_or_merge(repositories):
    plugin, project, _, _ = repositories
    (plugin / "local.txt").write_text("local commit\n")
    local = commit(plugin)
    git(plugin, "config", "pull.rebase", "true")
    git(plugin, "config", "pull.ff", "false")
    result = hook(plugin, project)
    assert "pull failed" in result["hookSpecificOutput"]["additionalContext"]
    assert git(plugin, "rev-parse", "HEAD") == local
    assert not (plugin / ".git/MERGE_HEAD").exists()
    assert not (plugin / ".git/rebase-merge").exists()


@pytest.mark.parametrize("state", ["detached", "no-upstream"])
def test_plugin_needs_attached_tracking_branch(repositories, state):
    plugin, project, baseline, _ = repositories
    if state == "detached":
        git(plugin, "checkout", "--detach", "-q")
    else:
        git(plugin, "branch", "--unset-upstream")
    result = hook(plugin, project)
    assert "configured upstream" in result["hookSpecificOutput"]["additionalContext"]
    assert git(plugin, "rev-parse", "HEAD") == baseline


def test_shell_hooks_and_packaged_copies_do_not_pull(repositories):
    plugin, project, baseline, _ = repositories
    assert hook(plugin, project, "PostToolUse") is None
    assert git(plugin, "rev-parse", "HEAD") == baseline
    cached = project / ".agents/understand-anything-plugin"
    cached.mkdir(parents=True)
    assert hook(cached, project) is None
    assert git(project, "rev-parse", "HEAD") == baseline


def test_timeout_kills_git_children(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("update_plugin", PLUGIN / "hooks/update_plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fake_git = tmp_path / "git"
    fake_git.write_text("#!/bin/sh\nsleep 20 &\nwait\n")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    with pytest.raises(subprocess.TimeoutExpired):
        module.git(tmp_path, "pull", timeout=0.1)
