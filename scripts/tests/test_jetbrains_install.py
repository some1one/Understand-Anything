"""Junie and AI Assistant install layouts, using only isolated fixture payloads."""
from pathlib import Path
import shutil
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALLERS = ["install.sh", "packaging/deb/understand-anything"]


@pytest.fixture
def payload(tmp_path):
    root = tmp_path / "fixture payload"
    for rel, text in {
        "skills/understand-help/SKILL.md": "---\nname: understand-help\ndescription: fixture\n---\n",
        "scripts/configure_dictionaries.py": "# Offline fixture: no configuration or downloads.\n",
        "tools/commands/fixture/run.sh": "#!/usr/bin/env bash\nprintf '%s\\n' 'fixture tool works'\n",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "tools/commands/fixture/run.sh").chmod(0o755)
    return root


def install_command(installer, payload, target, project=None):
    # Reuse a prepared fixture copy; never invoke a real installer copy/removal,
    # dependency bootstrap, native CLI, global link, or network operation.
    script = r'''source "$1" --help >/dev/null
fixture_payload="$2"
PLUGIN="$fixture_payload"
resolve_plugin_home() { printf '%s\n' "$fixture_payload"; }
find_assets() { return 1; }
check_prereqs() { :; }
native_available() { return 1; }
warm_env() { :; }
cmd_install "$3" "${4:-}"
'''
    return subprocess.run(
        ["bash", "-e", "-c", script, "test", str(REPO / installer), str(payload),
         target, *([str(project)] if project else [])],
        capture_output=True, text=True,
    )


@pytest.mark.parametrize("installer", INSTALLERS)
@pytest.mark.parametrize("target", ["junie", "jetbrains"])
def test_project_install_links_to_complete_local_payload(tmp_path, payload, installer, target):
    project = tmp_path / "project with spaces"
    local = project / ".agents/understand-anything-plugin"
    shutil.copytree(payload, local)
    (local / ".ua-assembled").touch()
    sentinel = project / "AGENTS.md"
    sentinel.write_text("Keep existing project instructions.\n")
    result = install_command(installer, payload, target, project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text() == "Keep existing project instructions.\n"
    expected = local / "skills/understand-help"
    assert (project / ".agents/skills/understand-help").resolve() == expected
    if target == "junie":
        assert (project / ".junie/skills/understand-help").resolve() == expected
    else:
        assert not (project / ".junie").exists()
    assert (expected / "SKILL.md").is_file()
    wrappers = list(project.glob(".*/tools/fixture"))
    assert len(wrappers) == 1
    output = subprocess.check_output([str(wrappers[0])], text=True)
    assert output == "fixture tool works\n"


@pytest.mark.parametrize("installer", INSTALLERS)
def test_jetbrains_requires_explicit_project_scope(payload, installer):
    result = install_command(installer, payload, "jetbrains")
    assert result.returncode != 0
    assert "project-only" in result.stderr
    assert "--local" in result.stderr


def test_installer_platform_tables_stay_in_sync():
    tables = [subprocess.check_output(
        ["bash", "-c", 'source "$1" --help >/dev/null; platforms_table', "test", str(REPO / installer)],
        text=True,
    ) for installer in INSTALLERS]
    assert tables[0] == tables[1]
    rows = {row.split("|", 1)[0]: row.split("|") for row in tables[0].splitlines()}
    assert rows["junie"][1] == str(Path.home() / ".junie/skills")
    assert rows["junie"][3:5] == [".junie/skills", "optional"]
    assert rows["jetbrains"][1] == ""
    assert rows["jetbrains"][3:5] == [".agents/skills", "required"]
