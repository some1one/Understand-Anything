"""Data updater rollback, provenance, and packaging/self-update wiring."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest
PLUGIN = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dictionary_updater', PLUGIN / 'scripts/update_dictionaries.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def snapshot(output, extra=None):
    return updater.publish(output, {'rust': ['RefCell']}, {'ran': {'VERB': ['run']}},
                           {'lemminflect.LICENSE': b'MIT License', 'cspell-rust.LICENSE': b'MIT License'},
                           {'cspell': {'revision': extra or 'a' * 40}, 'lemminflect': {'version': 'fixture'}})


def test_atomic_update_retains_previous_generation_on_failure(tmp_path, monkeypatch):
    initial = snapshot(tmp_path)
    before = (tmp_path / 'current.json').read_bytes()
    monkeypatch.setattr(updater, 'download_cspell', lambda: ({'rust': ['New']}, {}, {}))
    def fail():
        raise OSError('network unavailable')
    monkeypatch.setattr(updater, 'download_lemminflect', fail)
    assert updater.main(['--output', str(tmp_path)]) == 1
    assert (tmp_path / 'current.json').read_bytes() == before
    assert updater.validate(tmp_path) == initial
    assert updater.main(['--output', str(tmp_path), '--offline']) == 0
    updated = snapshot(tmp_path, 'b' * 40)
    assert initial['generation'] != updated['generation']
    assert (tmp_path / initial['generation'] / 'lemmas.json.gz').is_file()


def test_lemminflect_download_verifies_wheel_without_executing_code(monkeypatch):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('lemminflect/resources/lemma_lu.csv.gz', gzip.compress(b'ran,verb,run\ncan,modal,can\n'))
        archive.writestr('lemminflect/resources/lemma_overrides.csv', '# comment\nran,VERB,sprint\n')
        archive.writestr('lemminflect-99.dist-info/LICENSE', 'MIT License')
        archive.writestr('lemminflect/__init__.py', 'raise RuntimeError("must not execute")')
    wheel = out.getvalue()
    metadata = {'info': {'version': '99'}, 'urls': [{'filename': 'lemminflect-99-py3-none-any.whl',
                'url': 'https://files.pythonhosted.org/fixture.whl', 'digests': {'sha256': hashlib.sha256(wheel).hexdigest()}}]}
    monkeypatch.setattr(updater, 'fetch', lambda url: json.dumps(metadata).encode() if url.endswith('/json') else wheel)
    words, license_data, provenance = updater.download_lemminflect()
    assert words == {'ran': {'VERB': ['sprint']}, 'can': {'AUX': ['can']}}
    assert provenance['version'] == '99'
    assert license_data == b'MIT License'
    metadata['urls'][0]['digests']['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='checksum mismatch'):
        updater.download_lemminflect()


def test_cspell_resolves_latest_once_and_downloads_pinned_data(monkeypatch):
    monkeypatch.setattr(updater, 'NAMES', ['rust'])
    revision = 'c' * 40
    urls = []
    def fetch(url):
        urls.append(url)
        if url.endswith('/commits/main'):
            return json.dumps({'sha': revision}).encode()
        if '/git/trees/' in url:
            assert revision in url
            return json.dumps({'tree': [{'path': p, 'type': 'blob'} for p in [
                'dictionaries/rust/LICENSE', 'dictionaries/rust/dict/rust.txt',
                'dictionaries/rust/scripts/build.js']]}).encode()
        assert f'/{revision}/' in url
        return b'MIT License' if url.endswith('/LICENSE') else b'# comment\nRefCell\nArc\n!Arc\n'
    monkeypatch.setattr(updater, 'fetch', fetch)
    words, licenses, source = updater.download_cspell()
    assert words == {'rust': ['RefCell']}
    assert source['revision'] == revision
    assert licenses == {'cspell-rust.LICENSE': b'MIT License'}
    assert not any(url.endswith('build.js') for url in urls)


def test_installer_update_refreshes_dictionaries_after_successful_git_pull(tmp_path):
    script = '''source "$1" --help >/dev/null
UA_HOME="$2"
mkdir -p "$UA_HOME/repo/.git"
git() { printf 'git-update\\n'; }
python3() { printf 'dictionary-update:%s\\n' "$*"; }
cmd_update
'''
    result = subprocess.run(['bash', '-c', script, 'fixture', str(PLUGIN.parent / 'install.sh'), str(tmp_path)], capture_output=True, text=True, check=True)
    assert result.stdout.index('git-update') < result.stdout.index('dictionary-update:')
    assert str(tmp_path / 'repo/understand-anything-plugin/scripts/configure_dictionaries.py') in result.stdout
    failed = script.replace("printf 'git-update\\n';", 'return 1;')
    result = subprocess.run(['bash', '-c', failed, 'fixture', str(PLUGIN.parent / 'install.sh'), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'dictionary-update:' not in result.stdout


def test_bundling_never_downloads_dictionaries(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('dictionary_packager', PLUGIN.parent / 'scripts/build_dist.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    calls = []
    monkeypatch.setattr(builder, 'BUILD', tmp_path / 'build')
    monkeypatch.setattr(builder, 'DIST', tmp_path / 'dist')
    monkeypatch.setattr(builder, 'run', lambda cmd: calls.append(cmd))
    monkeypatch.setattr(builder, 'build_rust', lambda: calls.append('build') or Path('fixture'))
    monkeypatch.setattr(builder, 'assemble_payload', lambda *args, **kwargs: calls.append('assemble'))
    monkeypatch.setattr(builder, 'make_archives', lambda *args, **kwargs: [])
    import sys
    monkeypatch.setattr(sys, 'argv', ['build_dist.py', '--skip-dashboard'])
    assert builder.main() == 0
    assert calls == ['build', 'assemble']


def configurator(monkeypatch):
    import sys
    monkeypatch.syspath_prepend(str(PLUGIN / 'scripts'))
    spec = importlib.util.spec_from_file_location('dictionary_configurator', PLUGIN / 'scripts/configure_dictionaries.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'update_dictionaries', updater)
    return module


def test_system_discovery_uses_python_metadata_and_global_cspell_without_importing(tmp_path, monkeypatch):
    config = configurator(monkeypatch)
    resource = tmp_path / 'python/lemminflect/resources'
    resource.mkdir(parents=True)
    (resource / 'lemma_lu.csv.gz').write_bytes(gzip.compress(b'unsafe,adj,unsafe\n'))
    (resource / 'lemma_overrides.csv').write_text('')
    class Distribution:
        def locate_file(self, relative):
            return tmp_path / 'python' / relative
    monkeypatch.setattr(config.importlib.metadata, 'distribution', lambda name: Distribution())
    package = tmp_path / 'node_modules/@cspell/dict-software-terms/dict'
    package.mkdir(parents=True)
    (package / 'softwareTerms.txt.gz').write_bytes(gzip.compress(b'GET\nunsafe\n'))
    monkeypatch.setattr(config, 'node_roots', lambda: [tmp_path / 'node_modules'])
    monkeypatch.setattr(config, 'data_roots', lambda: [])
    result = config.discover()
    assert result['lemminflect']['lookup'] == str(resource / 'lemma_lu.csv.gz')
    assert result['cspell']['software-terms'] == [str(package / 'softwareTerms.txt.gz')]
    assert 'cspell/rust' in result['missing']
    assert 'cspell/software-terms' not in result['missing']


def test_all_system_data_never_downloads_and_partial_install_fetches_only_missing(tmp_path, monkeypatch):
    config = configurator(monkeypatch)
    monkeypatch.setattr(updater, 'NAMES', list(updater.NAMES))
    system = {'version': 1, 'lemminflect': {'lookup': '/installed/lookup', 'overrides': '/installed/overrides'},
              'cspell': {name: ['/installed/' + name] for name in config.NAMES}, 'missing': []}
    monkeypatch.setattr(config, 'discover', lambda: system.copy())
    def unexpected():
        raise AssertionError('System packages must not trigger downloads')
    monkeypatch.setattr(updater, 'download_cspell', unexpected)
    monkeypatch.setattr(updater, 'download_lemminflect', unexpected)
    path = tmp_path / 'configuration.json'
    local = tmp_path / 'local'
    args = ['--config', str(path), '--local-dir', str(local)]
    assert config.main(args) == 0
    assert json.loads(path.read_text())['snapshot'] == str(local)
    assert not local.exists()
    system['cspell'].pop('rust')
    system['missing'] = ['cspell/rust']
    def cspell():
        assert updater.NAMES == ['rust']
        return {'rust': ['unsafe']}, {}, {'revision': 'fixture'}
    monkeypatch.setattr(updater, 'download_cspell', cspell)
    assert config.main(args) == 0
    result = json.loads(path.read_text())
    assert result['snapshot'] == str(local)
    assert result['lemminflect'] == system['lemminflect']
    pointer = updater.validate(local)
    snapshot_dir = local / pointer['generation']
    assert json.loads(gzip.decompress((snapshot_dir / 'lemmas.json.gz').read_bytes())) == {}
    before = path.read_bytes(), (local / 'current.json').read_bytes()
    def failure():
        raise OSError('offline')
    monkeypatch.setattr(updater, 'download_cspell', failure)
    with pytest.raises(OSError, match='offline'):
        config.main(args)
    assert before == (path.read_bytes(), (local / 'current.json').read_bytes())


def test_rust_reads_system_data_and_trims_language_and_general_caches(tmp_path, monkeypatch):
    import os
    config = configurator(monkeypatch)
    root = tmp_path / 'project'
    state = root / '.understand-anything'
    state.mkdir(parents=True)
    graph = {'project': {'languages': ['Rust']}, 'nodes': [
        *[{'id': f'post{i}', 'name': f'Handler{i}', 'summary': 'POST requests'} for i in range(30)],
        {'id': 'target', 'name': 'ReadHandler', 'summary': 'GET requests'}]}
    (state / 'knowledge-graph.json').write_text(json.dumps(graph))
    lookup = tmp_path / 'lemma_lu.csv.gz'
    lookup.write_bytes(gzip.compress(b'unsafe,adj,unsafe\nGET,verb,GET\nget,verb,get\nbeautiful,adj,beautiful\n'))
    overrides = tmp_path / 'lemma_overrides.csv'
    overrides.write_text('')
    general = tmp_path / 'softwareTerms.txt.gz'
    general.write_bytes(gzip.compress(b'GET\nbeautiful\nhandler\n'))
    rust = tmp_path / 'rust.txt'
    rust.write_text('unsafe\nRefCell\n!forbidden\nforbidden\n')
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'version': 1, 'lemminflect': {'lookup': str(lookup), 'overrides': str(overrides)},
        'cspell': {'software-terms': [str(general)], 'rust': [str(rust)]}, 'snapshot': None}))
    binary = os.environ.get('UA_ENGINE_BINARY', str(PLUGIN / 'packages/rust/target/debug/understand-anything-rs'))
    env = dict(os.environ, UA_DICTIONARY_CONFIG=str(path), UA_DICTIONARY_DIR=str(tmp_path / 'absent'))
    subprocess.run([binary, 'refresh_query_dictionaries', str(root)], check=True, env=env, capture_output=True)
    manifest = json.loads((state / 'query-dictionaries/manifest.json').read_text())
    def words(name):
        return json.loads((state / 'query-dictionaries' / manifest['dictionaries'][name]['file']).read_text())
    assert words('rust') == ['unsafe']
    assert words('software-terms') == ['GET', 'beautiful']
    general.rename(tmp_path / 'disabled-general')
    rust.rename(tmp_path / 'disabled-rust')
    result = subprocess.run([binary, 'query_graph', str(root), 'GET requests'], capture_output=True, text=True, env=env, check=True)
    assert result.stderr == ''
    assert json.loads(result.stdout)['matchedNodes'] == [graph['nodes'][-1]]
    # Updated system lemma data invalidates trimmed technical caches.
    overrides.write_text('beautiful,NOUN,beautiful\n')
    result = subprocess.run([binary, 'query_graph', str(root), 'GET requests'], capture_output=True, text=True, env=env, check=True)
    assert 'lemma dictionary changed' in result.stderr


def test_system_version_checks_report_outdated_unknown_and_network_failures(tmp_path, monkeypatch, capsys):
    config = configurator(monkeypatch)
    packages = [
        {'name': 'lemminflect', 'registry': 'pypi', 'installed': '0.2.2'},
        {'name': '@cspell/dict-rust', 'registry': 'npm', 'installed': '4.2.0'},
        {'name': '@cspell/dict-python', 'registry': 'npm', 'installed': None},
        {'name': '@cspell/dict-java', 'registry': 'npm', 'installed': '1.0.0'},
    ]
    monkeypatch.setattr(config, 'installed_packages', lambda _: packages)
    calls = []
    def latest(package):
        calls.append(package['name'])
        if package['name'].endswith('java'):
            raise OSError('no network')
        return '0.2.3' if package['registry'] == 'pypi' else '4.2.0'
    monkeypatch.setattr(config, 'latest_version', latest)
    result = config.check_versions({})
    assert [r['status'] for r in result] == ['outdated', 'current-or-newer', 'installed-version-unavailable', 'check-failed']
    assert 'before indexing: installed 0.2.2, latest 0.2.3' in capsys.readouterr().err
    assert '@cspell/dict-python' not in calls
    calls.clear()
    assert all(r['status'] == 'not-checked-offline' for r in config.check_versions({}, offline=True))
    assert calls == []
    assert config.version_key('1.10.0') > config.version_key('1.9.0')
    assert config.version_key('1.2.0-rc.1') < config.version_key('1.2.0')


def test_local_only_preference_persists_and_can_return_to_system_discovery(tmp_path, monkeypatch):
    config = configurator(monkeypatch)
    monkeypatch.setattr(updater, 'NAMES', list(updater.NAMES))
    monkeypatch.setattr(config, 'check_versions', lambda *args, **kwargs: [])
    system = {'version': 1, 'lemminflect': {'lookup': '/system/lookup', 'overrides': '/system/overrides'},
              'cspell': {name: ['/system/' + name] for name in config.NAMES}}
    monkeypatch.setattr(config, 'discover', lambda: system.copy())
    monkeypatch.setattr(updater, 'download_cspell', lambda: ({'software-terms': ['GET']}, {}, {}))
    monkeypatch.setattr(updater, 'download_lemminflect', lambda: ({'get': {'VERB': ['get']}}, b'MIT', {}))
    path = tmp_path / 'config.json'
    local = tmp_path / 'repo/dictionaries'
    args = ['--config', str(path), '--local-dir', str(local)]
    assert config.main([*args, '--prefer-local']) == 0
    assert json.loads(path.read_text())['preferLocal'] is True
    assert config.main(['--config', str(path)]) == 0
    value = json.loads(path.read_text())
    assert value['lemminflect'] is None and value['cspell'] == {}
    assert value['snapshot'] == str(local)
    assert config.main(['--config', str(path), '--prefer-system']) == 0
    value = json.loads(path.read_text())
    assert value['preferLocal'] is False
    assert value['lemminflect'] == system['lemminflect']
    assert value['snapshot'] == str(local)


def test_runtime_system_dictionary_error_explains_both_repair_paths(tmp_path):
    import os
    state = tmp_path / '.understand-anything'
    state.mkdir()
    (state / 'knowledge-graph.json').write_text('{"nodes": []}')
    config = tmp_path / "dictionary config.json"
    config.write_text(json.dumps({'version': 1, 'lemminflect': {'lookup': str(tmp_path / 'missing.gz'),
        'overrides': str(tmp_path / 'missing.csv')}, 'cspell': {}}))
    binary = os.environ.get('UA_ENGINE_BINARY', str(PLUGIN / 'packages/rust/target/debug/understand-anything-rs'))
    result = subprocess.run([binary, 'query_graph', str(tmp_path), 'GET requests'], capture_output=True, text=True,
        env=dict(os.environ, UA_DICTIONARY_CONFIG=str(config)))
    assert result.returncode != 0 and result.stdout == ''
    for expected in [str(config), '--lemma-resources', '--cspell-root', '--prefer-local', '--local-dir', '/understand --full']:
        assert expected in result.stderr


def missing_system(config, monkeypatch):
    monkeypatch.setattr(config, 'discover', lambda: {'version': 1, 'lemminflect': None, 'cspell': {}})
    monkeypatch.setattr(config, 'check_versions', lambda *args, **kwargs: [])


def test_inspection_and_noninteractive_setup_never_choose_silently(tmp_path, monkeypatch, capsys):
    import io
    config = configurator(monkeypatch)
    missing_system(config, monkeypatch)
    monkeypatch.setattr(config.sys, 'stdin', io.StringIO(''))
    path = tmp_path / 'config.json'
    args = ['--config', str(path), '--project-root', str(tmp_path / 'project')]
    assert config.main([*args, '--inspect']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['missing'] and result['snapshot'] is None
    assert result['storageOptions']['repo'] == str(tmp_path / 'project/.understand-anything/dictionaries')
    assert not path.exists()
    with pytest.raises(ValueError, match='storage choice required'):
        config.main(args)
    assert not path.exists()


@pytest.mark.parametrize('answer,storage', [('1\n', 'shared'), ('2\n', 'repo')])
def test_prompt_choice_persists_and_manual_path_edit_is_respected(tmp_path, monkeypatch, answer, storage):
    import io
    config = configurator(monkeypatch)
    missing_system(config, monkeypatch)
    monkeypatch.setattr(config, 'shared_directory', lambda: tmp_path / 'shared')
    stream = io.StringIO(answer)
    monkeypatch.setattr(stream, 'isatty', lambda: True)
    monkeypatch.setattr(config.sys, 'stdin', stream)
    path = tmp_path / 'config.json'
    args = ['--config', str(path), '--project-root', str(tmp_path / 'project'), '--offline']
    assert config.main(args) == 0
    value = json.loads(path.read_text())
    assert value['storage'] == storage
    assert value['snapshot'] == str(tmp_path / ('shared' if storage == 'shared' else 'project/.understand-anything/dictionaries'))
    value['snapshot'] = str(tmp_path / 'manually changed path')
    path.write_text(json.dumps(value))
    monkeypatch.setattr(config.sys, 'stdin', io.StringIO(''))
    assert config.main(args) == 0
    assert json.loads(path.read_text())['snapshot'] == value['snapshot']


def test_complete_system_install_needs_no_storage_choice(tmp_path, monkeypatch):
    import io
    config = configurator(monkeypatch)
    monkeypatch.setattr(config, 'discover', lambda: {'version': 1,
        'lemminflect': {'lookup': '/system/lookup', 'overrides': '/system/overrides'},
        'cspell': {name: ['/system/' + name] for name in config.NAMES}})
    monkeypatch.setattr(config.sys, 'stdin', io.StringIO(''))
    path = tmp_path / 'config.json'
    assert config.main(['--config', str(path), '--offline']) == 0
    assert json.loads(path.read_text())['snapshot'] is None


def test_repo_download_is_ignored_and_keeps_project_caches_separate(tmp_path, monkeypatch):
    config = configurator(monkeypatch)
    missing_system(config, monkeypatch)
    monkeypatch.setattr(updater, 'NAMES', list(updater.NAMES))
    monkeypatch.setattr(updater, 'download_cspell', lambda: ({'rust': ['unsafe']}, {}, {}))
    monkeypatch.setattr(updater, 'download_lemminflect', lambda: ({'ran': {'VERB': ['run']}}, b'MIT', {}))
    project = tmp_path / 'project'
    project.mkdir()
    subprocess.run(['git', 'init', '-q', str(project)], check=True)
    query = project / '.understand-anything/query-dictionaries'
    query.mkdir(parents=True)
    (query / 'manifest.json').write_text('project data')
    path = tmp_path / 'config.json'
    assert config.main(['--config', str(path), '--storage', 'repo', '--project-root', str(project)]) == 0
    local = Path(json.loads(path.read_text())['snapshot'])
    updater.validate(local)
    subprocess.run(['git', '-C', str(project), 'check-ignore', str(local / 'current.json')], check=True)
    assert (query / 'manifest.json').read_text() == 'project data'


@pytest.mark.parametrize('platform,environment,suffix', [
    ('linux', {}, '.cache/understand-anything/dictionaries'),
    ('darwin', {}, 'Library/Caches/understand-anything/dictionaries'),
    ('linux', {'XDG_CACHE_HOME': '/custom/cache'}, '/custom/cache/understand-anything/dictionaries'),
    ('win32', {'LOCALAPPDATA': '/local/appdata'}, '/local/appdata/UnderstandAnything/Cache/dictionaries'),
])
def test_shared_storage_uses_os_location(monkeypatch, platform, environment, suffix):
    config = configurator(monkeypatch)
    monkeypatch.setattr(config.sys, 'platform', platform)
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    expected = Path(suffix) if suffix.startswith('/') else Path.home() / suffix
    assert config.shared_directory() == expected


def test_unattended_choice_preserves_saved_manual_location(tmp_path, monkeypatch):
    config = configurator(monkeypatch)
    missing_system(config, monkeypatch)
    monkeypatch.setenv('UA_DICTIONARY_STORAGE', 'shared')
    monkeypatch.setattr(config, 'shared_directory', lambda: tmp_path / 'shared')
    path = tmp_path / 'config.json'
    args = ['--config', str(path), '--offline']
    assert config.main(args) == 0
    assert json.loads(path.read_text())['snapshot'] == str(tmp_path / 'shared')
    value = json.loads(path.read_text())
    value['snapshot'] = str(tmp_path / 'manual')
    path.write_text(json.dumps(value))
    assert config.main(args) == 0
    assert json.loads(path.read_text())['snapshot'] == str(tmp_path / 'manual')
