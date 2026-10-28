#!/usr/bin/env python3
"""Prepare a marketplace plugin's native engine, parsers and dictionary data."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import configure_dictionaries


def is_plugin(path):
    try:
        return json.loads((path / '.claude-plugin/plugin.json').read_text()).get('name') == 'understand-anything'
    except (OSError, ValueError, AttributeError):
        return False


def asset_root(plugin):
    """Prefer the registered local marketplace source over a host's cached copy."""
    if os.environ.get('UA_PLUGIN_REPO'):
        candidate = Path(os.environ['UA_PLUGIN_REPO']).expanduser().resolve() / 'understand-anything-plugin'
        if is_plugin(candidate):
            return candidate
    if (plugin.parent / '.git').exists():
        return plugin
    host = 'codex' if '.codex' in plugin.parts else 'claude' if '.claude' in plugin.parts else None
    if host and shutil.which(host):
        try:
            result = subprocess.run([host, 'plugin', 'marketplace', 'list', '--json'],
                                    capture_output=True, text=True, timeout=5, check=True)
            data = json.loads(result.stdout)
            entries = data.get('marketplaces', []) if host == 'codex' else data
            for entry in entries:
                if entry.get('name') != 'understand-anything':
                    continue
                source = entry.get('marketplaceSource', {})
                local = source.get('source') if source.get('sourceType') == 'local' else entry.get('path') if entry.get('source') == 'directory' else None
                if local and is_plugin(candidate := Path(local).expanduser().resolve()) and os.access(candidate / 'packages/rust', os.W_OK):
                    return candidate
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
            pass
    if '.junie' in plugin.parts:
        try:
            entries = json.loads((Path.home() / '.junie/extensions/marketplaces.json').read_text())
            for entry in entries.values():
                source = entry.get('source', {})
                if source.get('type') == 'local' and source.get('path'):
                    candidate = Path(source['path']).expanduser().resolve()
                    if is_plugin(candidate) and os.access(candidate / 'packages/rust', os.W_OK):
                        return candidate
        except (OSError, ValueError, AttributeError):
            pass
    return plugin


def dictionary_config(plugin):
    if os.environ.get('UA_DICTIONARY_CONFIG'):
        return configure_dictionaries.config_path()
    rust = plugin / 'packages/rust'
    return rust / 'dictionary-config.json' if os.access(rust, os.W_OK) else configure_dictionaries.config_path()


def read_object(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def fingerprint(plugin, parsers, config):
    rust = plugin / 'packages/rust'
    paths = [rust / name for name in ['Cargo.toml', 'Cargo.lock', 'run.sh', 'parser-cache-dir', 'bin/understand-anything-rs', 'target/release/understand-anything-rs']]
    paths += list((rust / 'src').rglob('*.rs')) + list((rust / 'schemas').rglob('*.json')) + list((rust / 'reference').glob('*.json'))
    paths += [plugin / 'scripts' / name for name in ['setup_runtime.py', 'configure_dictionaries.py', 'update_dictionaries.py']]
    paths += [config] + [p for p in parsers.rglob('*') if p.is_file()]
    settings = read_object(config)
    lemmas = settings.get('lemminflect') or {}
    paths += [Path(value) for key, value in lemmas.items() if key in {'lookup', 'overrides'} and isinstance(value, str)]
    paths += [Path(value) for files in settings.get('cspell', {}).values() for value in files if isinstance(value, str)]
    snapshot = settings.get('snapshot')
    if snapshot:
        pointer = Path(snapshot) / 'current.json'
        paths.append(pointer)
        generation = read_object(pointer).get('generation')
        if isinstance(generation, str) and '/' not in generation and '\\' not in generation:
            paths += [p for p in (Path(snapshot) / generation).rglob('*') if p.is_file()]
    rows = []
    for path in sorted(set(paths)):
        if path.is_file():
            stat = path.stat()
            rows.append((str(path), stat.st_size, stat.st_mtime_ns))
    overrides = [os.environ.get('UA_DICTIONARY_DIR'), os.environ.get('UA_DICTIONARY_STORAGE')]
    return hashlib.sha256(json.dumps([str(parsers), str(config), overrides, rows]).encode()).hexdigest()


def run(command, plugin, deadline):
    process = subprocess.Popen(command, cwd=plugin, stdin=subprocess.DEVNULL,
                               stdout=sys.stderr, start_new_session=os.name == 'posix')
    try:
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def acquire(lock, deadline):
    if os.name == 'nt':
        import msvcrt
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b'0')
            lock.flush()
    else:
        import fcntl
    while True:
        try:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError('Another runtime setup is still running')
            time.sleep(0.1)


def prepare(plugin_root=None, force=False):
    plugin = Path(plugin_root or Path(__file__).resolve().parents[1]).resolve()
    if not is_plugin(plugin):
        raise ValueError(f'Not an Understand Anything plugin: {plugin}')
    rust = plugin / 'packages/rust'
    root = asset_root(plugin)
    parsers = Path(os.environ.get('UA_PARSER_CACHE_DIR', root / 'packages/rust/parsers')).expanduser().resolve()
    config = dictionary_config(plugin)
    if not config.is_absolute():
        config = (plugin / config).resolve()
    marker = rust / '.runtime-ready.json'
    binary = next((p for p in [rust / 'bin/understand-anything-rs', rust / 'target/release/understand-anything-rs'] if p.is_file()), None)
    if not force and binary and os.access(binary, os.X_OK) and read_object(marker).get('fingerprint') == fingerprint(plugin, parsers, config):
        return {'status': 'ready', 'prepared': False, 'pluginRoot': str(plugin), 'assetRoot': str(root)}
    # Serialize setup in a writable plugin/cache, not in the analyzed repository.
    deadline = time.monotonic() + 1500
    with (rust / '.runtime-setup.lock').open('a+b') as lock:
        acquire(lock, deadline)
        if not force and read_object(marker).get('fingerprint') == fingerprint(plugin, parsers, config):
            return {'status': 'ready', 'prepared': False, 'pluginRoot': str(plugin), 'assetRoot': str(root)}
        parsers.mkdir(parents=True, exist_ok=True)
        engine = rust / 'run.sh'
        commands = [[str(engine), '--version'], [str(engine), '--parser-cache-dir', str(parsers), 'parsers', 'fetch']]
        args = [sys.executable, str(plugin / 'scripts/configure_dictionaries.py'), '--plugin-root', str(plugin), '--config', str(config)]
        saved = read_object(config)
        if os.environ.get('UA_DICTIONARY_DIR'):
            args += ['--local-dir', str(Path(os.environ['UA_DICTIONARY_DIR']).expanduser().resolve())]
        elif not saved.get('snapshot') and not os.environ.get('UA_DICTIONARY_STORAGE'):
            args += ['--local-dir', str(Path(os.environ.get('UA_DICTIONARY_DIR', root / 'packages/rust/dictionaries')).expanduser().resolve())]
        # --storage repo must refer to the plugin source, never the caller's cwd.
        args += ['--project-root', str(root.parent)]
        commands.append(args)
        for command in commands:
            print('[understand-anything] Preparing runtime: ' + ' '.join(command), file=sys.stderr, flush=True)
            run(command, plugin, deadline)
        (rust / 'parser-cache-dir').write_text(str(parsers) + '\n')
        value = {'status': 'ready', 'prepared': True, 'pluginRoot': str(plugin), 'assetRoot': str(root),
                 'parserCache': str(parsers), 'dictionaryConfig': str(config), 'fingerprint': fingerprint(plugin, parsers, config)}
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2) + '\n')
        temporary.replace(marker)
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-root', type=Path)
    parser.add_argument('--force', action='store_true', help='recheck all runtime dependencies and assets')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.plugin_root, args.force)))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Runtime setup failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
