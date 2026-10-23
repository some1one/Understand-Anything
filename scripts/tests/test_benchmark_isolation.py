import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def test_output_aliases_and_workspace_boundary(tmp_path, monkeypatch):
    from benchmark.isolation import output_path, workspace
    subject = tmp_path / 'subject'
    subject.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(subject, target_is_directory=True)
    with pytest.raises(ValueError, match='inside-subject'):
        output_path(subject, alias / 'report.json')
    (tmp_path / 'public.md').symlink_to(subject / 'private.md')
    with pytest.raises(ValueError, match='inside-subject'):
        output_path(subject, tmp_path / 'public.json')
    import tempfile
    monkeypatch.setattr(tempfile, 'tempdir', str(subject))
    with pytest.raises(ValueError, match='temporary-directory-inside-subject'):
        workspace(subject)
    assert list(subject.iterdir()) == []


def test_input_symlink_escape_is_rejected(tmp_path):
    from benchmark.isolation import input_identity
    from benchmark.runner import StageError
    subject = tmp_path / 'subject'
    subject.mkdir()
    (tmp_path / 'private').write_text('secret')
    (subject / 'file.py').symlink_to(tmp_path / 'private')
    with pytest.raises(StageError, match='input-outside-subject'):
        input_identity(subject, [{'path': 'file.py'}])
