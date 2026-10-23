#!/usr/bin/env python3
"""Prefer installed dictionary data; manage local data only for missing components."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import re
import urllib.request
import urllib.parse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NAMES = ('cpp csharp css dart docker golang html java kotlin lua node php powershell '
         'python ruby rust scala shell software-terms sql swift terraform typescript').split()


sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_directory import data_dir

def config_path():
    return Path(os.environ.get('UA_DICTIONARY_CONFIG',
        Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) /
        'understand-anything/dictionaries.json'))


def shared_directory():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'UnderstandAnything/Cache/dictionaries'
    if os.environ.get('XDG_CACHE_HOME'):
        return Path(os.environ['XDG_CACHE_HOME']) / 'understand-anything/dictionaries'
    base = Path.home() / ('Library/Caches' if sys.platform == 'darwin' else '.cache')
    return base / 'understand-anything/dictionaries'


def select_storage(args, existing):
    if args.local_dir:
        return args.local_dir.expanduser().resolve(), 'custom'
    if not args.storage and existing.get('snapshot'):
        # The saved path is authoritative, including manual advanced-user edits.
        return Path(existing['snapshot']).expanduser().resolve(), existing.get('storage', 'custom')
    project = (args.project_root or Path.cwd()).expanduser().resolve()
    locations = {'shared': shared_directory(), 'repo': data_dir(project) / 'dictionaries'}
    choice = args.storage
    if not choice:
        if not sys.stdin.isatty():
            raise ValueError('Dictionary storage choice required: use --storage shared (recommended), '
                             '--storage repo --project-root /path/to/repo, or --local-dir /custom/path. '
                             'Use --inspect to check missing components without downloads or writes')
        print('Some system dictionaries are missing. Choose where to download them:', file=sys.stderr)
        print(f"  1. Shared user directory (recommended): {locations['shared']}", file=sys.stderr)
        print(f"  2. Local repo: {locations['repo']}", file=sys.stderr)
        while not choice:
            print('Storage [1=shared, 2=repo, q=cancel]: ', end='', file=sys.stderr, flush=True)
            answer = sys.stdin.readline()
            if not answer or answer.strip().lower() in {'q', 'cancel'}:
                raise ValueError('Dictionary setup cancelled; no storage location selected')
            choice = {'1': 'shared', 'shared': 'shared', '2': 'repo', 'repo': 'repo'}.get(answer.strip().lower())
    return locations[choice].expanduser().resolve(), choice


def find_lemmas():
    # Inspect distribution metadata without importing LemmInflect or its models.
    try:
        dist = importlib.metadata.distribution('lemminflect')
        root = Path(dist.locate_file('lemminflect/resources'))
        if all((root / n).is_file() for n in ('lemma_lu.csv.gz', 'lemma_overrides.csv')):
            return {'lookup': str((root / 'lemma_lu.csv.gz').resolve()),
                    'overrides': str((root / 'lemma_overrides.csv').resolve()),
                    'version': getattr(dist, 'version', None)}
    except importlib.metadata.PackageNotFoundError:
        pass
    return None


def data_roots():
    # Rust crates have no standard runtime dictionary registry. Inspect conventional
    # shared data locations, including CARGO_HOME, for compatible exported data.
    cargo = Path(os.environ.get('CARGO_HOME', Path.home() / '.cargo'))
    roots = [cargo / 'share', Path(sys.prefix) / 'share', Path('/usr/local/share'),
             Path('/usr/share'), Path.home() / '.local/share']
    return list(dict.fromkeys(roots))


def node_roots():
    roots = [Path(p) for p in os.environ.get('NODE_PATH', '').split(os.pathsep) if p]
    npm = shutil.which('npm')
    if npm:
        try:
            result = subprocess.run([npm, 'root', '-g'], capture_output=True, text=True,
                                    timeout=10, check=True)
            path = Path(result.stdout.strip())
            if path.is_absolute():
                roots.append(path)
        except (OSError, subprocess.SubprocessError):
            pass
    roots.extend([Path('/usr/local/lib/node_modules'), Path('/usr/lib/node_modules')])
    # CSpell may keep its bundled dependencies nested, rather than hoisted.
    for root in list(roots):
        roots.extend([root / 'cspell/node_modules', root / 'cspell/node_modules/cspell-bundled-dicts/node_modules',
                      root / 'cspell-bundled-dicts/node_modules'])
    return list(dict.fromkeys(roots))


def discover():
    result = {'version': 1, 'lemminflect': find_lemmas(), 'cspell': {}}
    roots = data_roots()
    if not result['lemminflect']:
        for root in roots:
            resource = root / 'lemminflect/resources'
            if all((resource / n).is_file() for n in ('lemma_lu.csv.gz', 'lemma_overrides.csv')):
                result['lemminflect'] = {'lookup': str((resource / 'lemma_lu.csv.gz').resolve()),
                    'overrides': str((resource / 'lemma_overrides.csv').resolve())}
                break
    nodes = node_roots()
    for name in NAMES:
        packages = [r / '@cspell' / f'dict-{name}' for r in nodes]
        packages += [r / 'cspell/dictionaries' / name for r in roots]
        for package in packages:
            # Published dictionaries use txt or txt.gz. Trie-only packages cannot
            # be read as word lists and are reported as unavailable.
            paths = sorted(set((package / 'dict').glob('*.txt')) |
                           set((package / 'dict').glob('*.txt.gz')))
            if paths:
                result['cspell'][name] = [str(p.resolve()) for p in paths]
                break
    result['missing'] = (["lemminflect"] if not result['lemminflect'] else []) + [
        f'cspell/{name}' for name in NAMES if name not in result['cspell']]
    return result


def installed_packages(config):
    packages = []
    if config['lemminflect']:
        packages.append({'name': 'lemminflect', 'registry': 'pypi',
                         'installed': config['lemminflect'].get('version')})
    for name, paths in config['cspell'].items():
        version = None
        if paths:
            metadata = Path(paths[0]).parent.parent / 'package.json'
            try:
                version = json.loads(metadata.read_text()).get('version')
            except (OSError, ValueError):
                pass
        packages.append({'name': '@cspell/dict-' + name, 'registry': 'npm', 'installed': version})
    return packages


def latest_version(package):
    url = ('https://pypi.org/pypi/lemminflect/json' if package['registry'] == 'pypi' else
           'https://registry.npmjs.org/' + urllib.parse.quote(package['name'], safe='') + '/latest')
    request = urllib.request.Request(url, headers={'User-Agent': 'Understand-Anything-dictionary-versions'})
    with urllib.request.urlopen(request, timeout=10) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Insecure version metadata redirect')
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Version metadata exceeds size limit')
    metadata = json.loads(raw)
    return metadata['info']['version'] if package['registry'] == 'pypi' else metadata['version']


def version_key(value):
    # Published stable versions and common PEP440/SemVer prereleases. Unknown
    # formats are reported as unverifiable instead of guessing version ordering.
    match = re.fullmatch(r'(\d+(?:\.\d+){0,3})(?:(a|b|rc|dev|-)[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', str(value))
    if not match:
        return None
    parts = tuple(int(v) for v in match[1].split('.'))
    return parts + (0,) * (4 - len(parts)) + (0 if match[2] else 1,)


def check_versions(config, offline=False):
    def check(package):
        result = dict(package)
        if offline:
            result['status'] = 'not-checked-offline'
        elif not version_key(package['installed']):
            result['status'] = 'installed-version-unavailable'
        else:
            try:
                latest = latest_version(package)
                result['latest'] = latest
                key = version_key(latest)
                result['status'] = ('outdated' if version_key(package['installed']) < key else 'current-or-newer') if key else 'latest-version-unavailable'
            except (OSError, ValueError, KeyError) as error:
                result.update(status='check-failed', error=str(error))
        return result
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, installed_packages(config)))
    for result in results:
        if result['status'] == 'outdated':
            print(f"Update system dictionary {result['name']} before indexing: installed {result['installed']}, latest {result['latest']}. Use its Python/npm/system package manager; no system package was changed.", file=sys.stderr)
        elif result['status'] != 'current-or-newer':
            print(f"System dictionary version not verified: {result['name']} ({result['status']}).", file=sys.stderr)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--plugin-root', type=Path)
    parser.add_argument('--local-dir', type=Path, help='Explicit custom download directory; saved in configuration')
    parser.add_argument('--storage', choices=('shared', 'repo'),
                        help='Download storage choice; defaults to saved choice or an interactive prompt')
    parser.add_argument('--project-root', type=Path, help='Repository for --storage repo; defaults to current directory')
    parser.add_argument('--inspect', action='store_true', help='Print discovery and saved storage as JSON without downloads or writes')
    parser.add_argument('--prefer-local', action='store_true', help='Persist local-only mode and download latest data instead of using system dictionaries')
    parser.add_argument('--prefer-system', action='store_true', help='Return to system-first discovery')
    parser.add_argument('--lemma-resources', type=Path, help='Use this installed LemmInflect resources directory')
    parser.add_argument('--cspell-root', type=Path, help='Use @cspell/dict-* packages under this node_modules directory')
    parser.add_argument('--offline', action='store_true', help='Discover and configure without refreshing local data')
    args = parser.parse_args(argv)
    if args.config is None:
        rust = args.plugin_root / 'packages/rust' if args.plugin_root else None
        args.config = (config_path() if os.environ.get('UA_DICTIONARY_CONFIG') else rust / 'dictionary-config.json' if rust and os.access(rust, os.W_OK)
                       else config_path())
    if args.prefer_local and args.prefer_system:
        parser.error('--prefer-local and --prefer-system are mutually exclusive')
    existing = json.loads(args.config.read_text()) if args.config.is_file() else {}
    if args.storage and args.local_dir:
        parser.error('--storage and --local-dir are alternatives')
    if not args.storage and not args.local_dir and not existing.get('snapshot'):
        args.storage = os.environ.get('UA_DICTIONARY_STORAGE')
        if args.storage not in {None, 'shared', 'repo'}:
            parser.error('UA_DICTIONARY_STORAGE must be shared or repo')
    local_only = args.prefer_local or (existing.get('preferLocal', False) and not args.prefer_system)
    config = ({'version': 1, 'lemminflect': None, 'cspell': {}} if local_only else discover())
    lemma_resources = args.lemma_resources or (Path(existing['lemmaResources']) if existing.get('lemmaResources') and not local_only else None)
    cspell_root = args.cspell_root or (Path(existing['cspellRoot']) if existing.get('cspellRoot') and not local_only else None)
    config['lemmaResources'] = str(lemma_resources.resolve()) if lemma_resources else None
    config['cspellRoot'] = str(cspell_root.resolve()) if cspell_root else None
    if lemma_resources:
        root = lemma_resources.resolve()
        if not all((root / n).is_file() for n in ('lemma_lu.csv.gz', 'lemma_overrides.csv')):
            parser.error('--lemma-resources must contain lemma_lu.csv.gz and lemma_overrides.csv')
        config['lemminflect'] = {'lookup': str(root / 'lemma_lu.csv.gz'), 'overrides': str(root / 'lemma_overrides.csv')}
    if cspell_root:
        for name in NAMES:
            root = cspell_root / '@cspell' / f'dict-{name}' / 'dict'
            files = sorted(set(root.glob('*.txt')) | set(root.glob('*.txt.gz')))
            if files:
                config['cspell'][name] = [str(p.resolve()) for p in files]
    config['preferLocal'] = local_only
    config['missing'] = (['lemminflect'] if not config['lemminflect'] else []) + [
        f'cspell/{name}' for name in NAMES if name not in config['cspell']]
    if args.inspect:
        print(json.dumps({**config, 'snapshot': existing.get('snapshot'), 'storage': existing.get('storage'),
                          'storageOptions': {'shared': str(shared_directory()),
                              'repo': str(data_dir((args.project_root or Path.cwd()).resolve()) / 'dictionaries')}}, indent=2))
        return 0
    # Preserve unrelated configuration fields.
    existing.update(config)
    config = existing
    local = None
    if config['missing'] or args.storage or args.local_dir:
        local, storage = select_storage(args, config)
        config['snapshot'] = str(local)
        config['storage'] = storage
    else:
        config.setdefault('snapshot', None)
    config['systemPackages'] = check_versions(config, offline=args.offline)
    if config['missing'] and not args.offline:
        if config['storage'] == 'repo':
            local.mkdir(parents=True, exist_ok=True)
            ignore = local / '.gitignore'
            if not ignore.exists():
                ignore.write_text('*\n')
        import update_dictionaries as updater
        # Fetch only unavailable packages; installed components stay external.
        updater.NAMES = [name for name in NAMES if name not in config['cspell']]
        words, licenses, provenance = {}, {}, {}
        if updater.NAMES:
            words, licenses, provenance['cspell'] = updater.download_cspell()
        lemmas = {}
        if not config['lemminflect']:
            lemmas, license_data, provenance['lemminflect'] = updater.download_lemminflect()
            licenses['lemminflect.LICENSE'] = license_data
        updater.publish(local, words, lemmas, licenses, provenance)
    args.config.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=args.config.parent, delete=False) as out:
        json.dump(config, out, indent=2)
        out.write('\n')
        temporary = Path(out.name)
    temporary.replace(args.config)
    print(f'Dictionary configuration: {args.config}')
    if config.get('snapshot'):
        print(f"Dictionary download directory (editable snapshot field): {config['snapshot']}")
    print(f'System LemmInflect: {bool(config["lemminflect"])}; CSpell dictionaries: {len(config["cspell"])}')
    if config['missing']:
        print('Unavailable dictionary data: ' + ', '.join(config['missing']), file=sys.stderr)
        print(('Offline: local fallback configured without downloads.' if args.offline else
               'Missing components use the managed local snapshot: ' + str(local)), file=sys.stderr)
    print('After updating Understand Anything or dictionary libraries, rebuild the index from scratch with /understand --full before relying on it.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print(f'Dictionary configuration/update failed: {error}. Previous configuration retained.', file=sys.stderr)
        raise SystemExit(1)
