"""Read-only subject identity and owned temporary artifact boundaries."""
import hashlib
import codecs
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .contract import digest
from .runner import StageError, RUST


def git_identity(root):
    def git(*args):
        result = subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args], capture_output=True)
        return result.stdout if result.returncode == 0 else None
    commit = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain=v1', '-z', '--untracked-files=all')
    return {'commit': commit.decode().strip() if commit else None,
            'dirty': bool(status) if status is not None else None}


def git_state_digest(root):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(root), 'status', '--porcelain=v1', '-z',
                             '--untracked-files=all'], capture_output=True)
    return hashlib.sha256(result.stdout).hexdigest() if result.returncode == 0 else None


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
    if Path(tempfile.gettempdir()).resolve().is_relative_to(subject):
        raise ValueError('temporary-directory-inside-subject')
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
    enumeration = subprocess.run(['git', '--no-optional-locks', '-C', str(subject), 'ls-files', '-co', '--exclude-standard', '-z'], capture_output=True)
    if enumeration.returncode == 0:
        # An ignore file can ignore its own filename and still affect siblings.
        # Inspect ancestors of enumerated files instead of assuming the ignore
        # files themselves appear in ls-files output.
        directories = {Path('.')}
        for name in set(enumeration.stdout.decode().split('\0')) - {''}:
            directories.update(Path(name).parents)
        for directory in sorted(directories):
            path = subject / directory / '.gitignore'
            if path.is_file() and directory != Path('.'):
                user.append(((directory / '.gitignore').as_posix(), hash_file(path)))
        # Worktrees can store info/exclude outside the subject; global rules can
        # also influence production git enumeration. Hash contents, never paths.
        for key, command in [('git-info-exclude', ['rev-parse', '--git-path', 'info/exclude']),
                             ('git-global-exclude', ['config', '--path', '--get', 'core.excludesfile'])]:
            value = subprocess.run(['git', '--no-optional-locks', '-C', str(subject), *command], capture_output=True, text=True)
            if value.returncode == 0 and value.stdout.strip():
                path = Path(value.stdout.strip()).expanduser()
                if not path.is_absolute():
                    path = subject / path
                if path.is_file():
                    user.append((key, hash_file(path)))
            elif key == 'git-global-exclude':
                path = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'git/ignore'
                if path.is_file():
                    user.append((key, hash_file(path)))
    return {'defaults': tables['languages']['DEFAULT_IGNORE_PATTERNS'] + ['.ua/', '.understand-anything/'],
            # User rules may contain identifying paths. Publish their content identity.
            'userFilesDigest': digest(user), 'invocation': exclusions,
            'gitEnumeration': enumeration.returncode == 0}


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
