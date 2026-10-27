"""Portable agent guidance and preservation of project-owned AGENTS.md content."""
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "understand-anything-plugin/skills/understand-agent-instructions"
SCRIPT = SKILL / "scripts/agent_instructions.py"
TEMPLATE = SKILL / "assets/agent-instructions.md"
START = b"<!-- understand-anything:agent-instructions:start -->"
END = b"<!-- understand-anything:agent-instructions:end -->"


def run(project, *args, check=True):
    return subprocess.run([sys.executable, str(SCRIPT), str(project), *args],
                          capture_output=True, check=check)


def test_print_uses_shared_template_without_changing_project(tmp_path):
    agents = tmp_path / "AGENTS.md"
    existing = b"# Project instructions\r\n\r\nPreserve my preferences.\r\n"
    agents.write_bytes(existing)
    output = run(tmp_path)
    assert output.stdout == TEMPLATE.read_bytes()
    assert agents.read_bytes() == existing
    assert list(tmp_path.iterdir()) == [agents]


@pytest.mark.parametrize("existing", [b"", b"# Project\nKeep me.", b"# Project\r\nKeep me.\r\n"])
def test_write_preserves_existing_bytes_and_is_idempotent(tmp_path, existing):
    project = tmp_path / "project with spaces"
    project.mkdir()
    agents = project / "AGENTS.md"
    if existing:
        agents.write_bytes(existing)
    run(project, "--write")
    updated = agents.read_bytes()
    assert updated.startswith(existing)
    assert updated.count(START) == updated.count(END) == 1
    run(project, "--write")
    assert agents.read_bytes() == updated
    assert list(project.iterdir()) == [agents]


def test_update_replaces_only_dedicated_section(tmp_path):
    agents = tmp_path / "AGENTS.md"
    prefix = b"# Project\r\nDo not change this section.\r\n\r\n"
    suffix = b"\r\n\r\n## Testing\r\nKeep these commands.\r\n"
    agents.write_bytes(prefix + START + b"\nOld guidance.\n" + END + suffix)
    run(tmp_path, "--write")
    assert agents.read_bytes() == prefix + TEMPLATE.read_bytes().rstrip(b"\n") + suffix


@pytest.mark.parametrize("markers", [START, END, END + START, START + END + START + END])
def test_malformed_sections_fail_without_writing(tmp_path, markers):
    agents = tmp_path / "AGENTS.md"
    existing = b"# Project\n" + markers
    agents.write_bytes(existing)
    result = run(tmp_path, "--write", check=False)
    assert result.returncode != 0
    assert agents.read_bytes() == existing


def test_write_does_not_follow_agents_symlink(tmp_path):
    target = tmp_path / "shared.md"
    target.write_text("Shared instructions\n")
    (tmp_path / "AGENTS.md").symlink_to(target)
    result = run(tmp_path, "--write", check=False)
    assert result.returncode != 0
    assert target.read_text() == "Shared instructions\n"
