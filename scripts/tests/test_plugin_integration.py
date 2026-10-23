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


def test_distribution_contains_native_engine_and_shared_references(tmp_path):
    builder = load_module(REPO / "scripts/build_dist.py")
    binary = PLUGIN / "packages/rust/target/release/understand-anything-rs"
    if not binary.exists():
        pytest.skip("Rust release binary has not been built")
    payload = tmp_path / "payload"
    builder.assemble_payload(payload, binary)
    for relative in [".claude-plugin/plugin.json", ".codex-plugin/plugin.json",
                     "HOSTS.md", "hooks/auto_update.py", "scripts/create_marketplace.py",
                     "packages/rust/run.sh", "packages/rust/bin/understand-anything-rs",
                     "packages/rust/schemas/knowledge-graph.schema.json",
                     "packages/dashboard/freshness-server.mjs"]:
        assert (payload / relative).is_file(), relative
    assert (payload / "AGENTS.md").read_text() == (PLUGIN / "AGENTS.md").read_text()
    assert len(list((payload / "skills").glob("*/SKILL.md"))) == 13
    assert not (payload / "packages/core").exists()
    result = subprocess.run(["bash", str(payload / "packages/rust/run.sh"), "--version"],
                            check=True, capture_output=True, text=True)
    assert "understand-anything-rs" in result.stdout


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


@pytest.mark.parametrize("existing", [True, False])
def test_installer_git_fallback_returns_only_path(tmp_path, existing):
    ua_home = tmp_path / "ua home"
    if existing:
        (ua_home / "repo/.git").mkdir(parents=True)
    script = '''source "$1" --help >/dev/null
SCRIPT_DIR="$2/standalone"
UA_HOME="$2/ua home"
UA_REPO_URL=https://example.invalid/plugin.git
find_assets() { return 1; }
git() { printf 'mock git progress\\n' >&2; }
plugin="$(resolve_plugin_home)"
printf '%s' "$plugin"
'''
    result = subprocess.run(["bash", "-c", script, "test", str(REPO / "install.sh"), str(tmp_path)],
                            capture_output=True, text=True, check=True)
    assert result.stdout == str(ua_home / "repo/understand-anything-plugin")
    assert ("Updating" if existing else "Cloning") in result.stderr


@pytest.mark.parametrize("default_branch", ["main", "master", "trunk"])
def test_diff_context_default_feature_base_and_working_tree(tmp_path, default_branch):
    module = load_module(PLUGIN / "skills/understand-diff/scripts/diff_context.py")

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, text=True, capture_output=True, check=True)

    git("init", "-q", "-b", default_branch)
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Fixture")
    (tmp_path / "base.txt").write_text("base\n")
    git("add", ".")
    git("commit", "-qm", "base")
    if default_branch == "trunk":
        git("update-ref", "refs/remotes/origin/trunk", "HEAD")
        git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    git("checkout", "-qb", "feature")
    (tmp_path / "feature.txt").write_text("feature\n")
    git("add", ".")
    git("commit", "-qm", "feature")
    files, label = module.changed_files(tmp_path, None)
    assert files == ["feature.txt"]
    assert label == ("origin/trunk" if default_branch == "trunk" else default_branch)
    assert module.changed_files(tmp_path, default_branch) == (["feature.txt"], default_branch)
    git("checkout", "-q", default_branch)
    (tmp_path / "base.txt").write_text("staged\n")
    git("add", ".")
    assert module.changed_files(tmp_path, None) == (["base.txt"], "working-tree")
    (tmp_path / "base.txt").write_text("unstaged\n")
    assert module.changed_files(tmp_path, None) == (["base.txt"], "working-tree")


@pytest.mark.parametrize("native_mode", ["success", "failure", "unavailable"])
def test_archive_install_reuses_configured_payload(tmp_path, native_mode):
    script = r'''source "$1" --help >/dev/null
UA_HOME="$2/ua home"
SCRIPT_DIR="$2/archive"
mkdir -p "$SCRIPT_DIR"
# Model assembly replacing dictionary state, without downloading or installing.
find_assets() { return 0; }
# Keep the real resolver, including its per-install resolved-payload reuse.
assemble_into() {
  local plugin="$1/understand-anything-plugin"
  mkdir -p "$plugin/scripts"
  printf 'assembly\n' >> "$UA_HOME/assemblies"
  printf 'unconfigured' > "$plugin/state"
  printf '%s\n' "$plugin"
}
check_prereqs() { :; }
python3() {
  case "$1" in
    */configure_dictionaries.py) printf 'configured' > "$3/state" ;;
    */create_marketplace.py) printf '%s\n' "$3" ;;
  esac
}
native_available() { [ "$mode" != unavailable ]; }
native_install() {
  local plugin
  plugin="$(marketplace_source)" || return 1
  [ "$(cat "$plugin/state")" = configured ] || return 1
  [ "$mode" = success ]
}
link_skills_global() { [ "$(cat "$1/state")" = configured ]; }
link_plugin_root() { :; }
warm_env() { :; }
mode="$3"
cmd_install claude
[ "$(cat "$UA_HOME/understand-anything-plugin/state")" = configured ]
[ "$(wc -l < "$UA_HOME/assemblies")" -eq 1 ]
'''
    subprocess.run(["bash", "-e", "-c", script, "test", str(REPO / "install.sh"),
                    str(tmp_path), native_mode], check=True, capture_output=True, text=True)
