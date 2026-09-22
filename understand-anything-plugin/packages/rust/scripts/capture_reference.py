"""Capture the working-tree Python baseline; development only, never runtime."""
import ast
import hashlib
import importlib.metadata
import json
import pathlib
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parents[1]
CORE = HERE.parent / 'core'
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def capture():
    if (HERE/"reference/baseline.json").exists() and "--replace-baseline" not in sys.argv:
        raise SystemExit("Baseline already exists; explicit --replace-baseline is required to replace it")
    files = sorted([*CORE.glob('understand_core/**/*.py'), *CORE.glob('skill_builders/**/*.py')])
    schemas = sorted(CORE.glob('understand_core/schemas/*.json'))
    project = tomllib.loads((CORE / 'pyproject.toml').read_text())
    aliases = {}
    for alias, script in project['tool']['pdm']['scripts'].items():
        aliases.setdefault(script['cmd'].split('understand_core.')[-1], []).append(alias)
    modules = []
    for path in files:
        source = path.read_text()
        tree = ast.parse(source)
        executable = any(isinstance(n, ast.If) and '__name__' in ast.unparse(n.test) for n in tree.body)
        modules.append({'python': str(path.relative_to(CORE)), 'sha256': digest(path),
                        'lines': len(source.splitlines()), 'command': path.stem if executable else None,
                        'aliases': aliases.get(path.stem, []),
                        'public_symbols': [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith('_')],
                        'rust': None, 'tests': [], 'status': 'pending'})
    versions = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}
    baseline = {'modules': modules, 'schemas': {p.name: digest(p) for p in schemas},
                'dependencies': dict(sorted(versions.items())),
                'dependency_files': {p.name: digest(p) for p in [CORE/'pyproject.toml', CORE/'pdm.lock'] if p.exists()}}
    (HERE/'reference/baseline.json').write_text(json.dumps(baseline, indent=2)+'\n')
    for p in schemas:
        (HERE/'schemas'/p.name).write_bytes(p.read_bytes())
    print(f'{len(files)} modules, {sum(m["lines"] for m in modules)} lines, {sum(bool(m["command"]) for m in modules)} commands, {len(schemas)} schemas')

if __name__ == '__main__':
    capture()
