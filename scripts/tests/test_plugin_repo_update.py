"""Startup checks use local remotes without updating checkout or Git refs."""
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
        env={**os.environ, "UA_PLUGIN_REPO": str(plugin), "UA_SKIP_RUNTIME_SETUP": "1"},
    )
    return json.loads(result.stdout) if result.stdout else None


def test_session_start_reports_available_update_without_changing_either_repository(repositories):
    plugin, project, baseline, latest = repositories
    refs_before = git(plugin, "show-ref")
    status_before = git(plugin, "status", "--porcelain")
    result = hook(plugin, project)
    context = result["hookSpecificOutput"]["additionalContext"]
    assert "update may be available" in context
    assert latest[:12] in context
    assert "confirm" in context and "pull --ff-only" in context
    assert "Do not start" in context
    assert git(plugin, "rev-parse", "HEAD") == baseline
    assert git(plugin, "show-ref") == refs_before
    assert git(plugin, "status", "--porcelain") == status_before
    assert git(project, "rev-parse", "HEAD") == baseline
    assert (project / "source.txt").read_text() == "original\n"
    assert hook(plugin, project)  # Repeated checks do not apply the update.


@pytest.mark.parametrize("dirty", ["untracked", "staged", "unstaged"])
def test_dirty_plugin_is_not_pulled_or_stashed(repositories, dirty):
    plugin, project, baseline, _ = repositories
    path = plugin / ("new.txt" if dirty == "untracked" else "source.txt")
    path.write_text("local work\n")
    if dirty == "staged":
        git(plugin, "add", "source.txt")
    before = git(plugin, "status", "--porcelain")
    result = hook(plugin, project)
    assert "update may be available" in result["hookSpecificOutput"]["additionalContext"]
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
    assert "update may be available" in result["hookSpecificOutput"]["additionalContext"]
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
    assert ("attached branch" if state == "detached" else "configured upstream") in result["hookSpecificOutput"]["additionalContext"]
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


def test_plugin_update_has_one_shared_timeout_budget(monkeypatch, repositories):
    import importlib.util
    plugin, _, _, _ = repositories
    spec = importlib.util.spec_from_file_location("bounded_update_plugin", PLUGIN / "hooks/update_plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('UA_PLUGIN_REPO', str(plugin))
    elapsed = [0]
    calls = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: elapsed[0])
    def fake_git(root, *args, timeout):
        calls.append(timeout)
        elapsed[0] += 3
        output = str(plugin) if args[0] == 'rev-parse' else 'origin\0refs/heads/main' if args[0] == 'for-each-ref' else 'refs/heads/main'
        return subprocess.CompletedProcess(args, 0, output, '')
    monkeypatch.setattr(module, 'git', fake_git)
    assert 'timed out' in module.check_plugin_update()
    assert len(calls) == 3
    assert all(timeout <= 2 for timeout in calls)


def test_current_or_locally_ahead_plugin_has_no_update_notice(repositories):
    plugin, project, _, latest = repositories
    git(plugin, "pull", "--ff-only")  # Explicit fixture update; never done by hook.
    assert git(plugin, "rev-parse", "HEAD") == latest
    assert hook(plugin, project) is None
    (plugin / "ahead.txt").write_text("local commit\n")
    commit(plugin)
    before = git(plugin, "rev-parse", "HEAD")
    assert hook(plugin, project) is None
    assert git(plugin, "rev-parse", "HEAD") == before


def test_only_session_start_is_registered():
    hooks = json.loads((PLUGIN / 'hooks/hooks.json').read_text())['hooks']
    assert set(hooks) == {'SessionStart'}
    assert hooks['SessionStart'][0]['hooks'][0]['timeout'] <= 20
