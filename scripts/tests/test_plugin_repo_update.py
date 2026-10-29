"""POSIX startup notices never wait for stdin or launch language runtimes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / 'understand-anything-plugin'
HOOK = PLUGIN / 'hooks/check_version.sh'


@pytest.fixture
def hook_env(tmp_path):
    # Only POSIX utilities and a fake curl: no Node, Python, or Git.
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in ['sh', 'dirname', 'sed', 'head', 'awk', 'date', 'mkdir']:
        (bin_dir / name).symlink_to(shutil.which(name))
    curl = bin_dir / 'curl'
    curl.write_text('''#!/bin/sh
printf '%s\\n' "$@" >> "$CURL_LOG"
if [ "$CURL_FAIL" = 1 ]; then exit 28; fi
printf '{"version":"%s"}\\n' "${PUBLISHED_VERSION-2.9.0}"
''')
    curl.chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir),
           'XDG_CACHE_HOME': str(tmp_path / 'user cache'),
           'CURL_LOG': str(tmp_path / 'curl.log')}
    env.pop('UA_SKIP_UPDATE_CHECK', None)
    return env


def invoke(env, hook=HOOK):
    return subprocess.run(['/bin/sh', str(hook)], env=env, text=True,
                          capture_output=True, check=True, timeout=3)


def cache_file(env):
    return Path(env['XDG_CACHE_HOME']) / 'understand-anything/published-version.json'


def write_cache(env, version, checked_at=None):
    cache = cache_file(env)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'checkedAt': int(time.time() * 1000)
                                if checked_at is None else checked_at, 'version': version}))


@pytest.mark.parametrize('host', ['claude', 'codex'])
def test_packaged_hook_uses_its_own_version_and_never_touches_project(tmp_path, hook_env, host):
    packaged = tmp_path / 'packaged plugin with spaces'
    (packaged / 'hooks').mkdir(parents=True)
    (packaged / '.claude-plugin').mkdir()
    shutil.copy2(HOOK, packaged / 'hooks/check_version.sh')
    shutil.copy2(PLUGIN / 'hooks/hooks.json', packaged / 'hooks/hooks.json')
    (packaged / '.claude-plugin/plugin.json').write_text(json.dumps({'version': '2.8.1'}))
    if host == 'codex':
        manifest = json.loads((PLUGIN / '.codex-plugin/plugin.json').read_text())
        assert manifest['hooks'] == './hooks/hooks.json'
        hooks_file = packaged / manifest['hooks']
        hook_env['PLUGIN_ROOT'] = str(packaged)
    else:
        hooks_file = packaged / 'hooks/hooks.json'
    hook_env['CLAUDE_PLUGIN_ROOT'] = str(packaged)
    handler = json.loads(hooks_file.read_text())['hooks']['SessionStart'][0]['hooks'][0]
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'source.txt').write_text('existing work')
    result = subprocess.run(['/bin/sh', '-c', handler['command']],
                            input=json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(project)}),
                            cwd=project, env=hook_env, capture_output=True, text=True, check=True,
                            timeout=3)
    output = json.loads(result.stdout)
    assert '2.9.0' in output['systemMessage'] and '2.8.1' in output['systemMessage']
    assert output['hookSpecificOutput']['hookEventName'] == 'SessionStart'
    assert output['hookSpecificOutput']['additionalContext'] == output['systemMessage']
    assert not result.stderr
    assert list(project.iterdir()) == [project / 'source.txt']
    assert (project / 'source.txt').read_text() == 'existing work'


@pytest.mark.parametrize('version,notice', [
    ('2.8.2', True), ('2.10.0', True), ('3.0.0', True),
    ('2.8.1', False), ('2.7.99', False), ('1.99.99', False),
    ('2.9.0-beta', False), ('bad', False), ('', False),
    ('9999999999999999999.0.0', False),
])
def test_numeric_stable_versions_only(hook_env, version, notice):
    hook_env['PUBLISHED_VERSION'] = version
    result = invoke(hook_env)
    assert bool(result.stdout) is notice
    assert not result.stderr


@pytest.mark.parametrize('failed', [False, True])
def test_success_and_failure_are_cached_for_a_day(hook_env, failed):
    if failed:
        hook_env['CURL_FAIL'] = '1'
    first = invoke(hook_env)
    calls = Path(hook_env['CURL_LOG']).read_text()
    assert calls.startswith('-q\n')
    assert '--max-time\n1\n' in calls
    assert '--connect-timeout\n1\n' in calls
    assert '--max-filesize\n16384\n' in calls
    assert invoke(hook_env).stdout == first.stdout
    assert Path(hook_env['CURL_LOG']).read_text() == calls
    write_cache(hook_env, '', 0)
    invoke(hook_env)
    assert Path(hook_env['CURL_LOG']).read_text() == calls * 2


@pytest.mark.parametrize('checked_at', [0, 'invalid', int(time.time() * 1000) + 86400000])
def test_invalid_expired_and_future_cache_refresh(hook_env, checked_at):
    write_cache(hook_env, '2.8.1', checked_at)
    assert '2.9.0' in invoke(hook_env).stdout


def test_failed_refresh_keeps_previous_notice(hook_env):
    write_cache(hook_env, '2.9.0', 0)
    hook_env['CURL_FAIL'] = '1'
    assert '2.9.0' in invoke(hook_env).stdout


def test_corrupt_and_unwritable_cache_are_nonfatal(hook_env):
    cache_file(hook_env).parent.mkdir(parents=True)
    cache_file(hook_env).write_text('broken')
    assert '2.9.0' in invoke(hook_env).stdout
    hook_env['XDG_CACHE_HOME'] = str(cache_file(hook_env) / 'child')
    result = invoke(hook_env)
    assert '2.9.0' in result.stdout
    assert not result.stderr


def test_opt_out_does_no_work(hook_env):
    hook_env['UA_SKIP_UPDATE_CHECK'] = '1'
    result = invoke(hook_env)
    assert not result.stdout and not result.stderr
    assert not Path(hook_env['CURL_LOG']).exists()
    assert not cache_file(hook_env).exists()


def test_missing_curl_is_silent(hook_env):
    Path(hook_env['PATH'], 'curl').unlink()
    result = invoke(hook_env)
    assert not result.stdout and not result.stderr


def test_handler_exits_without_waiting_for_host_stdin(hook_env):
    # Keep the parent's pipe open throughout wait(), including an uncached check.
    process = subprocess.Popen(['/bin/sh', str(HOOK)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=hook_env)
    try:
        assert process.wait(timeout=2) == 0
        assert '2.9.0' in process.stdout.read().decode()
        assert not process.stderr.read()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


def test_only_background_shell_session_start_is_registered():
    hooks = json.loads((PLUGIN / 'hooks/hooks.json').read_text())['hooks']
    assert set(hooks) == {'SessionStart'}
    [handler] = hooks['SessionStart'][0]['hooks']
    assert handler['command'] == 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/check_version.sh"'
    assert handler['async'] is True
    assert handler['timeout'] == 3
