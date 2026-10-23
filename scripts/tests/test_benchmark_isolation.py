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


def test_effective_default_global_and_hidden_nested_git_ignores(tmp_path, monkeypatch):
    import subprocess
    from benchmark.isolation import ignore_identity
    subject = tmp_path / 'subject'
    subject.mkdir()
    subprocess.run(['git', 'init', '-q', str(subject)], check=True)
    nested = subject / 'nested'
    nested.mkdir()
    (nested / 'code.py').write_text('print(1)')
    ignore = nested / '.gitignore'
    ignore.write_text('.gitignore\nhidden.py\n')
    config = tmp_path / 'config'
    (config / 'git').mkdir(parents=True)
    global_ignore = config / 'git/ignore'
    global_ignore.write_text('global-hidden.py\n')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    a = ignore_identity(subject, [])
    ignore.write_text('.gitignore\nhidden.py\n# same effective matches\n')
    b = ignore_identity(subject, [])
    assert a['userFilesDigest'] != b['userFilesDigest']
    global_ignore.write_text('global-hidden.py\n# same effective matches\n')
    c = ignore_identity(subject, [])
    assert b['userFilesDigest'] != c['userFilesDigest']
