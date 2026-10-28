"""Marketplace setup builds and places language assets without touching a project."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / 'understand-anything-plugin'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def runtime(tmp_path):
    plugin = tmp_path / 'plugin source' / 'understand-anything-plugin'
    rust = plugin / 'packages/rust'
    write(plugin / '.claude-plugin/plugin.json', '{"name":"understand-anything"}')
    write(rust / 'Cargo.toml', 'fixture')
    write(rust / 'Cargo.lock', 'fixture')
    write(rust / 'src/lib.rs', 'fixture')
    write(rust / 'reference/tables.json', '{}')
    (rust / 'schemas').mkdir()
    scripts = plugin / 'scripts'
    scripts.mkdir()
    shutil.copy2(PLUGIN / 'scripts/setup_runtime.py', scripts / 'setup_runtime.py')
    shutil.copy2(PLUGIN / 'packages/rust/run.sh', rust / 'run.sh')
    calls = tmp_path / 'calls.jsonl'
    engine = write(tmp_path / 'engine-template', f'''#!{sys.executable}
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['UA_FIXTURE_CALLS'], 'a') as out: out.write(json.dumps(['engine', *args])+'\\n')
cache = None
while '--parser-cache-dir' in args:
    i=args.index('--parser-cache-dir'); cache=args[i+1]; del args[i:i+2]
if args == ['--version']: print('fixture engine')
elif args == ['parsers', 'fetch']:
    if os.environ.get('UA_FIXTURE_FAIL'): sys.exit(23)
    root=pathlib.Path(cache); root.mkdir(parents=True,exist_ok=True); (root/'fixture-parser.so').write_text('parser')
else: sys.exit(24)
''')
    engine.chmod(0o755)
    bin_dir = tmp_path / 'bin'
    cargo = write(bin_dir / 'cargo', f'''#!{sys.executable}
import json, os, pathlib, shutil, sys
with open(os.environ['UA_FIXTURE_CALLS'],'a') as out: out.write(json.dumps(['cargo',*sys.argv[1:]])+'\\n')
p=pathlib.Path('target/release/understand-anything-rs'); p.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(os.environ['UA_FIXTURE_ENGINE'],p)
os.utime(p,None)
''')
    cargo.chmod(0o755)
    configure = write(scripts / 'configure_dictionaries.py', '''import argparse, json, os
from pathlib import Path
def config_path(): return Path(os.environ['UA_DICTIONARY_CONFIG'])
if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--plugin-root'); p.add_argument('--config'); p.add_argument('--local-dir'); p.add_argument('--project-root')
    a=p.parse_args(); target=Path(a.config); existing=json.loads(target.read_text()) if target.exists() else {}
    local=Path(a.local_dir or existing['snapshot']); local.mkdir(parents=True,exist_ok=True)
    (local/'current.json').write_text('{"generation":"fixture"}')
    (local/'fixture').mkdir(exist_ok=True); (local/'fixture/lemmas.json.gz').write_text('fixture')
    target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps({'snapshot':str(local)}))
    with open(os.environ['UA_FIXTURE_CALLS'],'a') as out: out.write(json.dumps(['dictionaries',str(local)])+'\\n')
''')
    env = {k: v for k, v in os.environ.items() if k not in {'UA_PLUGIN_REPO', 'UA_PARSER_CACHE_DIR', 'UA_DICTIONARY_CONFIG', 'UA_DICTIONARY_DIR', 'UA_DICTIONARY_STORAGE'}}
    env.update(PATH=str(bin_dir)+os.pathsep+os.environ['PATH'], UA_FIXTURE_CALLS=str(calls), UA_FIXTURE_ENGINE=str(engine))
    project = tmp_path / 'analyzed project'
    project.mkdir()
    return plugin, calls, env, project, bin_dir


def setup(runtime, extra=(), env=None, check=True):
    plugin, _, default_env, project, _ = runtime
    return subprocess.run([sys.executable, str(plugin / 'scripts/setup_runtime.py'), '--plugin-root', str(plugin), *extra],
                          cwd=project, env=env or default_env, capture_output=True, text=True, check=check)


def test_setup_builds_once_and_reuses_ready_assets(runtime):
    plugin, calls, _, project, _ = runtime
    result = json.loads(setup(runtime).stdout)
    assert result['prepared']
    assert Path(result['parserCache']) == plugin / 'packages/rust/parsers'
    assert json.loads(Path(result['dictionaryConfig']).read_text())['snapshot'] == str(plugin / 'packages/rust/dictionaries')
    steps = [json.loads(row) for row in calls.read_text().splitlines()]
    assert steps[0] == ['cargo', '+stable', 'build', '--locked', '--release']
    before = calls.read_bytes()
    assert not json.loads(setup(runtime).stdout)['prepared']
    assert calls.read_bytes() == before
    assert list(project.iterdir()) == []


def test_embedded_reference_change_rebuilds_the_engine(runtime):
    plugin, calls, _, _, _ = runtime
    setup(runtime)
    before = sum(json.loads(row)[0] == 'cargo' for row in calls.read_text().splitlines())
    (plugin / 'packages/rust/reference/tables.json').write_text('{"updatedDefaults":true}')
    assert json.loads(setup(runtime).stdout)['prepared']
    after = sum(json.loads(row)[0] == 'cargo' for row in calls.read_text().splitlines())
    assert after == before + 1


def test_cached_local_marketplace_uses_source_repository_for_languages(runtime, tmp_path):
    plugin, calls, env, project, bin_dir = runtime
    source = tmp_path / 'registered source/understand-anything-plugin'
    write(source / '.claude-plugin/plugin.json', '{"name":"understand-anything"}')
    (source / 'packages/rust').mkdir(parents=True)
    cached = tmp_path / '.codex/plugins/cache/understand-anything/2.8.1'
    cached.parent.mkdir(parents=True)
    shutil.move(str(plugin), cached)
    codex = write(bin_dir / 'codex', f'''#!{sys.executable}
import json
print(json.dumps({{'marketplaces':[{{'name':'understand-anything','marketplaceSource':{{'sourceType':'local','source':{str(source)!r}}}}}]}}))
''')
    codex.chmod(0o755)
    new_runtime = cached, calls, env, project, bin_dir
    result = json.loads(setup(new_runtime).stdout)
    assert result['assetRoot'] == str(source)
    assert Path(result['parserCache']).is_relative_to(source)
    assert json.loads(Path(result['dictionaryConfig']).read_text())['snapshot'] == str(source / 'packages/rust/dictionaries')
    assert (cached / 'packages/rust/parser-cache-dir').read_text().strip() == str(source / 'packages/rust/parsers')
    assert not (cached / 'packages/rust/parsers').exists()
    assert list(project.iterdir()) == []


def test_saved_dictionary_location_and_parser_override_are_preserved(runtime, tmp_path):
    plugin, _, env, _, _ = runtime
    chosen = tmp_path / 'custom dictionaries'
    write(plugin / 'packages/rust/dictionary-config.json', json.dumps({'snapshot':str(chosen)}))
    env['UA_PARSER_CACHE_DIR'] = str(tmp_path / 'custom parsers')
    result = json.loads(setup(runtime).stdout)
    assert result['parserCache'] == env['UA_PARSER_CACHE_DIR']
    assert json.loads(Path(result['dictionaryConfig']).read_text())['snapshot'] == str(chosen)


def test_relative_config_override_is_anchored_to_plugin_not_analyzed_project(runtime):
    plugin, _, env, project, _ = runtime
    env['UA_DICTIONARY_CONFIG'] = 'settings/custom.json'
    result = json.loads(setup(runtime).stdout)
    assert result['dictionaryConfig'] == str(plugin / 'settings/custom.json')
    assert not (project / 'settings').exists()


def test_dictionary_environment_override_invalidates_ready_setup(runtime, tmp_path):
    _, _, env, _, _ = runtime
    setup(runtime)
    chosen = tmp_path / 'explicit dictionary override'
    env['UA_DICTIONARY_DIR'] = str(chosen)
    result = json.loads(setup(runtime).stdout)
    assert result['prepared']
    assert json.loads(Path(result['dictionaryConfig']).read_text())['snapshot'] == str(chosen)


def test_failed_fetch_is_not_marked_ready_and_retry_finishes(runtime):
    plugin, _, env, _, _ = runtime
    failed = setup(runtime, env={**env,'UA_FIXTURE_FAIL':'1'}, check=False)
    assert failed.returncode != 0
    assert not (plugin / 'packages/rust/.runtime-ready.json').exists()
    assert json.loads(setup(runtime).stdout)['status'] == 'ready'


def test_missing_parser_or_runtime_binding_repeats_setup(runtime):
    plugin, _, _, _, _ = runtime
    setup(runtime)
    parser = plugin / 'packages/rust/parsers/fixture-parser.so'
    parser.rename(parser.with_suffix('.old'))
    assert json.loads(setup(runtime).stdout)['prepared']
    binding = plugin / 'packages/rust/parser-cache-dir'
    binding.rename(binding.with_suffix('.old'))
    assert json.loads(setup(runtime).stdout)['prepared']


def test_explicit_parser_argument_overrides_recorded_default(runtime, tmp_path):
    plugin, _, env, _, _ = runtime
    setup(runtime)
    chosen = tmp_path / 'explicit parser cache'
    subprocess.run([str(plugin / 'packages/rust/run.sh'), '--parser-cache-dir', str(chosen), 'parsers', 'fetch'],
                   env=env, check=True, capture_output=True)
    assert (chosen / 'fixture-parser.so').is_file()


@pytest.mark.parametrize('event', ['SessionStart', 'PostToolUse'])
def test_hook_initializes_runtime_only_on_session_start(monkeypatch, capsys, event):
    import importlib.util
    import io
    monkeypatch.syspath_prepend(str(PLUGIN / 'hooks'))
    spec = importlib.util.spec_from_file_location('runtime_hook', PLUGIN / 'hooks/auto_update.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.delenv('UA_SKIP_RUNTIME_SETUP', raising=False)
    monkeypatch.setattr(module, 'update_plugin', lambda: calls.append('pull'))
    monkeypatch.setattr(module, 'prepare', lambda: (calls.append('prepare') or {'prepared':True,'assetRoot':'/plugin-source'}))
    monkeypatch.setattr(module, 'context_for', lambda event: None)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'hook_event_name':event})))
    module.main()
    output = capsys.readouterr().out
    if event == 'SessionStart':
        assert calls == ['pull','prepare']
        assert 'Runtime ready' in json.loads(output)['systemMessage']
    else:
        assert calls == []
        assert not output
