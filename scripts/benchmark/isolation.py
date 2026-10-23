"""Read-only subject identity and owned temporary artifact boundaries."""
import hashlib
import codecs
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .contract import digest
from .runner import StageError, ROOT, RUST


def git_identity(root):
    def git(*args):
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
        return result.stdout if result.returncode == 0 else None
    commit = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain=v1', '-z', '--untracked-files=all')
    return {'commit': commit.decode().strip() if commit else None,
            'dirty': bool(status) if status is not None else None}


def output_path(subject, output):
    # Resolve existing parent aliases as well as a symlink at the final filename.
    output = Path(output).resolve()
    if output.suffix != '.json':
        raise ValueError('output-must-be-json')
    for path in (output, output.with_suffix('.md'), output.with_suffix('.lock')):
        if path.resolve().is_relative_to(subject):
            raise ValueError('output-inside-subject')
        if path.is_symlink():
            raise ValueError('output-symlink')
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise ValueError('output-must-be-independent-file')
    return output


def workspace(subject):
    path = Path(tempfile.mkdtemp(prefix='ua-benchmark-')).resolve()
    if path.is_relative_to(subject):
        # Empty owned directory only; no subject contents are touched.
        path.rmdir()
        raise ValueError('temporary-directory-inside-subject')
    return path


def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def assets_identity(cache):
    # Require an explicit preconfigured cache so identity never depends on HOME.
    cache = Path(cache).resolve()
    libs = cache / 'tree-sitter-language-pack/v1.20.0/libs'
    if not libs.is_dir():
        raise ValueError('parser-assets-not-preconfigured')
    assets = sorted(p for p in libs.iterdir() if p.is_file())
    if not assets:
        raise ValueError('parser-assets-empty')
    return digest([(p.name, hash_file(p)) for p in assets])


def ignore_identity(subject, exclusions):
    tables = json.loads((RUST / 'reference/tables.json').read_text())
    user = []
    data = '.ua' if (subject / '.ua').is_dir() or not (subject / '.understand-anything').is_dir() else '.understand-anything'
    for rel in (data + '/.understandignore', '.understandignore', '.gitignore', '.git/info/exclude'):
        path = subject / rel
        if path.is_file():
            user.append((rel, hash_file(path)))
    return {'defaults': tables['languages']['DEFAULT_IGNORE_PATTERNS'] + ['.ua/', '.understand-anything/'],
            # User rules may contain identifying paths. Publish their content identity.
            'userFilesDigest': digest(user), 'invocation': exclusions,
            'gitEnumeration': subprocess.run(['git', '-C', str(subject), 'rev-parse', '--is-inside-work-tree'], capture_output=True).returncode == 0}


def input_identity(subject, files):
    result = []
    unreadable = 0
    for file in files:
        relative = Path(file['path'])
        path = (subject / relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(subject):
            raise StageError('input-outside-subject')
        try:
            h = hashlib.sha256()
            decoder = codecs.getincrementaldecoder('utf-8')()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(block)
                    decoder.decode(block)
                decoder.decode(b'', final=True)
            result.append((file['path'], h.hexdigest()))
        except (OSError, UnicodeError):
            unreadable += 1
    if unreadable:
        raise StageError('input-unreadable', count=unreadable)
    return digest(result)
