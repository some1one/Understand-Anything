"""Host contracts and installation fixtures; no user host configuration is changed."""
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "understand-anything-plugin"
SCRIPTS = PLUGIN / "skills/understand/scripts"


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # A symbolic HEAD is enough for rev-parse; no fixture commit is created.
    (root / ".git/HEAD").write_text("ref: refs/heads/fixture\n")
    (root / ".git/refs/heads/fixture").write_text("a" * 40 + "\n")
    write_json(root / ".understand-anything/config.json", {"autoUpdate": True, "includedParts": ["src"]})
    write_json(root / ".understand-anything/meta.json", {"gitCommitHash": "b" * 40})
    write_json(root / ".understand-anything/knowledge-graph.json", {"nodes": []})
    return root


def run_hook(event):
    return subprocess.run(
        [sys.executable, str(PLUGIN / "hooks/auto_update.py")],
        input=json.dumps(event), text=True, capture_output=True, check=True,
    ).stdout


@pytest.mark.parametrize("event_name", ["SessionStart", "PostToolUse"])
def test_host_hook_context_and_no_writes(project, event_name):
    before = {p: p.read_bytes() for p in (project / ".understand-anything").iterdir()}
    nested = project / "src"
    nested.mkdir()
    output = json.loads(run_hook({"hook_event_name": event_name, "tool_name": "Bash", "cwd": str(nested), "tool_input": {"command": "git commit -m example"}}))
    context = output["hookSpecificOutput"]
    assert context["hookEventName"] == event_name
    assert str(project) in context["additionalContext"]
    assert str(PLUGIN / "hooks/auto-update-prompt.md") in context["additionalContext"]
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_hook_requires_boolean_opt_in(project, value):
    write_json(project / ".understand-anything/config.json", {"autoUpdate": value})
    assert not run_hook({"hook_event_name": "SessionStart", "cwd": str(project)})


def test_hook_current_missing_malformed_and_unrelated(project):
    event = {"hook_event_name": "SessionStart", "cwd": str(project)}
    write_json(project / ".understand-anything/meta.json", {"gitCommitHash": "a" * 40})
    assert not run_hook(event)
    (project / ".understand-anything/config.json").write_text("invalid json")
    assert not run_hook(event)
    assert not run_hook([])
    assert not run_hook({"hook_event_name": []})
    assert not run_hook({"hook_event_name": "PostToolUse", "tool_name": {}})
    assert not run_hook({"hook_event_name": "PostToolUse", "tool_name": "Read", "cwd": str(project)})
    assert not run_hook({"hook_event_name": "SessionStart", "cwd": "/nonexistent"})


def test_config_toggle_preserves_partition_selection(project):
    for flag, expected in [("--no-auto-update", False), ("--auto-update", True)]:
        subprocess.run(["bash", str(SCRIPTS / "prepare_workspace.sh"), str(project), flag], check=True)
        assert json.loads((project / ".understand-anything/config.json").read_text()) == {"autoUpdate": expected, "includedParts": ["src"]}


def test_cleanup_preserves_summary_and_scan(project):
    inter = project / ".understand-anything/intermediate"
    for name in ["save-summary.json", "scan-result.json", "batch-1.json"]:
        write_json(inter / name, {"name": name})
    subprocess.run(["bash", str(SCRIPTS / "cleanup_intermediate.sh"), str(project)], check=True)
    assert (inter / "save-summary.json").exists()
    assert (inter / "scan-result.json").exists()
    assert not (inter / "batch-1.json").exists()
    assert list((project / ".understand-anything").glob(".trash-*/batch-1.json"))


def test_marketplace_contracts_and_existing_directory(tmp_path):
    module = load_module(PLUGIN / "scripts/create_marketplace.py")
    root = module.create_marketplace(tmp_path / "catalog", PLUGIN)
    assert module.create_marketplace(root, PLUGIN) == root
    for catalog in [".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"]:
        entry = json.loads((root / catalog).read_text())["plugins"][0]
        source = entry["source"]
        relative = source if isinstance(source, str) else source["path"]
        assert (root / relative).resolve() == PLUGIN
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="unowned"):
        module.create_marketplace(unrelated, PLUGIN)
    assert (unrelated / "keep.txt").read_text() == "keep"


def test_dashboard_resolution_with_spaces_and_stale_host_root(tmp_path):
    plugin = tmp_path / "plugin with spaces"
    script = plugin / "skills/understand-dashboard/scripts/resolve_dashboard.sh"
    script.parent.mkdir(parents=True)
    script.write_text((PLUGIN / script.relative_to(plugin)).read_text())
    (plugin / "packages/dashboard").mkdir(parents=True)
    result = subprocess.run(["bash", "-c", 'eval "$(bash "$1")"; printf "%s" "$DASHBOARD_DIR"', "test", str(script)],
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "PLUGIN_ROOT": str(PLUGIN)},
        check=True, capture_output=True, text=True)
    assert result.stdout == str(plugin / "packages/dashboard")


def test_architecture_input_uses_analyzed_nodes_only(project):
    write_json(project / ".understand-anything/intermediate/scan-result.json", {"languages": [], "frameworks": []})
    nodes = [{"id": "file:src/custom.py", "type": "file", "name": "custom.py", "filePath": "src/custom.py", "summary": "Actual analyzed node", "tags": ["python"]}]
    write_json(project / ".understand-anything/intermediate/assembled-graph.json", {"nodes": nodes, "edges": []})
    (project / "excluded.py").write_text("pass\n")
    subprocess.run([sys.executable, str(SCRIPTS / "prepare_architecture_context.py"), str(project), str(SCRIPTS.parent)], check=True)
    payload = json.loads((project / ".understand-anything/tmp/ua-arch-input.json").read_text())
    assert payload["fileNodes"] == nodes


def test_project_root_keeps_requested_checkout(project):
    result = subprocess.run(["bash", str(SCRIPTS / "resolve_project_root.sh"), str(project)], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == str(project)


@pytest.mark.parametrize("installer", ["install.sh", "packaging/deb/understand-anything"])
@pytest.mark.parametrize("host", ["claude", "codex"])
def test_failed_native_install_is_not_mistaken_for_catalog_listing(installer, host):
    script = '''source "$1" --help >/dev/null
marketplace_source() { printf '/fixture/catalog\\n'; }
claude() { case "$*" in 'plugin install '*) return 1;; *) printf 'understand-anything\\n';; esac; }
codex() { case "$*" in 'plugin add '*) return 1;; *) printf 'understand-anything\\n';; esac; }
native_install "$2" ""
'''
    result = subprocess.run(["bash", "-c", script, "test", str(REPO / installer), host], capture_output=True, text=True)
    assert result.returncode != 0


@pytest.mark.parametrize("installer", ["install.sh", "packaging/deb/understand-anything"])
def test_claude_uninstall_uses_project_scope(installer, project):
    script = '''source "$1" --help >/dev/null
claude() { printf '%s\\n' "$*"; }
native_uninstall claude "$2"
'''
    result = subprocess.run(["bash", "-c", script, "test", str(REPO / installer), str(project)], check=True, capture_output=True, text=True)
    assert "plugin uninstall understand-anything@understand-anything --scope project" in result.stdout


def test_distribution_contains_both_hosts_and_shared_references(tmp_path):
    builder = load_module(REPO / "scripts/build_dist.py")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("")
    payload = tmp_path / "payload"
    builder.assemble_payload(payload, requirements)
    for relative in [".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "HOSTS.md", "hooks/auto_update.py", "scripts/create_marketplace.py", "packages/core/run.sh"]:
        assert (payload / relative).is_file(), relative
    assert (payload / "AGENTS.md").read_text() == (PLUGIN / "AGENTS.md").read_text()
    assert len(list((payload / "skills").glob("*/SKILL.md"))) == 11
    assert not (payload / "packages/core/.pdm-python").exists()
    assert not (payload / "packages/core/.pdm-build").exists()


def test_auto_update_discovers_split_batch_outputs(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PLUGIN / "packages/core"))
    from understand_core.auto_update_apply_batches import _discover_batch_files
    for name in ["batch-2-part-10.json", "batch-2-part-2.json", "batch-1.json", "batch-existing.json", "batch-invalid.json"]:
        write_json(tmp_path / name, {"nodes": [], "edges": []})
    assert [p.name for p in _discover_batch_files(tmp_path)] == ["batch-1.json", "batch-2-part-2.json", "batch-2-part-10.json"]


@pytest.mark.parametrize("fail", [False, True])
def test_source_bootstrap_ignores_saved_python_and_preserves_old_env(tmp_path, fail):
    core = tmp_path / "cached core"
    core.mkdir()
    (core / "run.sh").write_text((PLUGIN / "packages/core/run.sh").read_text())
    (core / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    (core / ".pdm-python").write_text("/unrelated/checkout/python")
    old = core / ".venv"
    old.mkdir()
    (old / "keep.txt").write_text("recoverable")
    bins = tmp_path / "bin"
    bins.mkdir()
    pdm = bins / "pdm"
    pdm.write_text('#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\nPath("pdm-call.json").write_text(json.dumps({"argv": sys.argv[1:], "env": {key: value for key, value in os.environ.items() if key.startswith("PDM_")}}))\nsys.exit(' + str(int(fail)) + ')\n')
    pdm.chmod(0o755)
    result = subprocess.run(["bash", str(core / "run.sh"), "--ensure"], env={**os.environ, "PATH": str(bins) + os.pathsep + os.environ["PATH"]}, capture_output=True, text=True)
    assert (result.returncode != 0) == fail, result.stderr
    call = json.loads((core / "pdm-call.json").read_text())
    assert call["argv"] == ["install", "--frozen-lockfile", "--prod", "--no-self"]
    assert call["env"]["PDM_PYTHON"] == str(core / ".venv/bin/python")
    assert call["env"]["PDM_IGNORE_SAVED_PYTHON"] == "1"
    assert call["env"]["PDM_IGNORE_ACTIVE_VENV"] == "1"
    assert list(core.glob(".venv-recovery.*/venv/keep.txt"))
    assert (core / ".venv/bin/python").exists() != fail


def test_packaged_bootstrap_is_offline_with_bundled_wheelhouse(tmp_path):
    core = tmp_path / "packaged core"
    core.mkdir()
    (core / "run.sh").write_text((PLUGIN / "packages/core/run.sh").read_text())
    (core / "requirements.txt").write_text("")
    (core / "wheelhouse").mkdir()
    (core / "wheelhouse/unused.whl").touch()
    result = subprocess.run(["bash", str(core / "run.sh"), "--ensure"], env={**os.environ, "PIP_INDEX_URL": "http://127.0.0.1:1/unreachable", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_RETRIES": "0"}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "trying online" not in result.stderr
    assert (core / ".venv/bin/python").exists()


def test_markdown_relative_links_and_host_frontmatter():
    import yaml
    files = [REPO / "README.md", REPO / "AGENTS.md", REPO / "CLAUDE.md"]
    files += [p for p in PLUGIN.rglob("*.md") if not {".venv", "node_modules", ".pytest_cache"}.intersection(p.parts)]
    assert len(files) >= 90
    for path in files:
        text = path.read_text()
        for target in re.findall(r"\]\(([^\s)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            assert (path.parent / target.split("#")[0]).exists(), (path, target)
        if path.name == "SKILL.md" or path.parent == PLUGIN / "agents":
            fields = yaml.safe_load(text.split("---", 2)[1])
            assert isinstance(fields["name"], str)
            assert isinstance(fields["description"], str)
            if "argument-hint" in fields:
                assert isinstance(fields["argument-hint"], str)


@pytest.mark.parametrize("kind", ["language", "framework"])
def test_all_prompt_loader_references(kind):
    skill = PLUGIN / f"skills/understand-{kind}"
    for prompt in (skill / "prompts").glob("*.md"):
        output = subprocess.run([sys.executable, str(skill / "scripts/load_prompt.py"), prompt.stem], check=True, capture_output=True, text=True)
        assert prompt.read_text().strip() in output.stdout
