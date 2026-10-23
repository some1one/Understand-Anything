"""The Python and shell entrypoints must select the same complete snapshot."""
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "understand-anything-plugin"


@pytest.mark.parametrize("existing, selected", [([], ".ua"), ([".understand-anything"], ".understand-anything"), ([".ua", ".understand-anything"], ".ua")])
def test_workspace_and_metadata_follow_directory_selection(tmp_path, existing, selected):
    project = tmp_path / "project with spaces"
    project.mkdir()
    for name in existing:
        (project / name).mkdir()
    resolved = subprocess.check_output(
        [sys.executable, str(PLUGIN / "scripts/data_directory.py"), str(project)], text=True
    ).strip()
    assert resolved == str(project / selected)
    assert sorted(p.name for p in project.iterdir()) == sorted(existing)
    subprocess.run(["bash", str(PLUGIN / "skills/understand/scripts/prepare_workspace.sh"), str(project), "--auto-update"], check=True)
    subprocess.run([sys.executable, str(PLUGIN / "skills/understand/scripts/write_meta.py"), str(project), "a" * 40, "3"], check=True)
    assert (project / selected / "intermediate").is_dir()
    assert (project / selected / "tmp").is_dir()
    assert (project / selected / "config.json").is_file()
    assert (project / selected / "meta.json").is_file()
    other = ".understand-anything" if selected == ".ua" else ".ua"
    assert not (project / other / "meta.json").exists()
