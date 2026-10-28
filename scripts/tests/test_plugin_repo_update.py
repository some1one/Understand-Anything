"""Dependency-free version notices never run Git, setup or project maintenance."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / 'understand-anything-plugin'
HOOK = PLUGIN / 'hooks/check_version.mjs'
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node is required for startup hooks')


def test_version_cache_and_event_contracts():
    subprocess.run([NODE, '--test', str(Path(__file__).with_name('startup_version.test.mjs'))],
                   check=True, capture_output=True, text=True)


@pytest.fixture
def hook_env(tmp_path):
    cache = tmp_path / 'user cache' / 'understand-anything'
    cache.mkdir(parents=True)
    (cache / 'published-version.json').write_text(json.dumps({
        'checkedAt': int(time.time() * 1000), 'version': '999.0.0',
    }))
    # No Git, Python, npm or other executables are available to the hook.
    env = {**os.environ, 'PATH': '', 'XDG_CACHE_HOME': str(cache.parent)}
    env.pop('UA_SKIP_UPDATE_CHECK', None)
    env.pop('NODE_OPTIONS', None)
    return env


@pytest.mark.parametrize('host', ['claude', 'codex'])
def test_packaged_hook_uses_its_own_version_and_never_touches_project(tmp_path, hook_env, host):
    packaged = tmp_path / 'packaged plugin with spaces'
    (packaged / 'hooks').mkdir(parents=True)
    (packaged / '.claude-plugin').mkdir()
    shutil.copy2(HOOK, packaged / 'hooks/check_version.mjs')
    shutil.copy2(PLUGIN / 'hooks/hooks.json', packaged / 'hooks/hooks.json')
    (packaged / '.claude-plugin/plugin.json').write_text(json.dumps({'version': '2.8.1'}))
    if host == 'codex':
        manifest = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())
        assert manifest['hooks'] == './hooks/hooks.json'
        hooks_file = packaged / manifest['hooks']
        hook_env['PLUGIN_ROOT'] = str(packaged)
    else:
        hooks_file = packaged / 'hooks/hooks.json'  # Claude's discovery convention.
    # Codex supplies this compatibility variable as well as PLUGIN_ROOT.
    hook_env['CLAUDE_PLUGIN_ROOT'] = str(packaged)
    handler = json.loads(hooks_file.read_text())['hooks']['SessionStart'][0]['hooks'][0]
    command = handler['command'].replace('node ', shlex.quote(NODE) + ' ', 1)
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'source.txt').write_text('existing work')
    result = subprocess.run(['/bin/sh', '-c', command],
                            input=json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(project)}),
                            cwd=project, env=hook_env, capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert '999.0.0' in output['systemMessage'] and '2.8.1' in output['systemMessage']
    assert output['hookSpecificOutput']['hookEventName'] == 'SessionStart'
    assert not result.stderr
    assert list(project.iterdir()) == [project / 'source.txt']
    assert (project / 'source.txt').read_text() == 'existing work'


@pytest.mark.parametrize('payload', ['invalid', '[]', '{}', '{"hook_event_name":"PostToolUse"}'])
def test_invalid_and_unrelated_events_are_silent(payload, hook_env):
    result = subprocess.run([NODE, str(HOOK)], input=payload, env=hook_env,
                            text=True, capture_output=True, check=True)
    assert not result.stdout and not result.stderr


def test_handler_exits_if_host_never_closes_stdin(hook_env):
    started = time.monotonic()
    process = subprocess.Popen([NODE, str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=hook_env)
    try:
        assert process.wait(timeout=3) == 0
        assert time.monotonic() - started < 2.5
        assert not process.stdout.read() and not process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


def test_network_timeout_and_stalled_dns_are_bounded(tmp_path, hook_env):
    # Replace HTTPS with a stalled request. Even an OS lookup that does not finish
    # after destroy() cannot outlive the CLI's hard deadline. No live network.
    preload = tmp_path / 'stalled-network.mjs'
    preload.write_text('''import https from 'node:https';
import { EventEmitter } from 'node:events';
import { syncBuiltinESMExports } from 'node:module';
https.get = () => {
  const request = new EventEmitter();
  request.destroy = () => {};
  setInterval(() => {}, 10000);
  return request;
};
syncBuiltinESMExports();
''')
    hook_env['XDG_CACHE_HOME'] = str(tmp_path / 'empty cache')
    started = time.monotonic()
    result = subprocess.run([NODE, '--import', str(preload), str(HOOK)],
                            input='{"hook_event_name":"SessionStart"}', env=hook_env,
                            text=True, capture_output=True, check=True, timeout=3)
    assert 1 <= time.monotonic() - started < 2.5
    assert not result.stdout and not result.stderr


def test_only_background_session_start_is_registered():
    hooks = json.loads((PLUGIN / 'hooks/hooks.json').read_text())['hooks']
    assert set(hooks) == {'SessionStart'}
    [handler] = hooks['SessionStart'][0]['hooks']
    assert handler['command'] == 'node "${CLAUDE_PLUGIN_ROOT}/hooks/check_version.mjs"'
    assert handler['async'] is True
    assert handler['timeout'] == 3
