"""Verify phase boundaries and real process metrics without downloads or model calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from benchmark import full_run
from benchmark.codex_analysis import command


def config_without_model(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{"analysisCommand": null}')
    return path


def test_plan_is_read_only_and_separates_builds_from_packaging(tmp_path):
    output = tmp_path / 'results'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/benchmark/full_run.py'), str(tmp_path / 'subject'),
                             '--output-dir', str(output), '--plan'], capture_output=True, text=True)
    assert result.returncode == 2  # no implicit creation of a missing subject
    subject = tmp_path / 'subject'
    subject.mkdir()
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/benchmark/full_run.py'), str(subject),
                             '--output-dir', str(output), '--plan'], capture_output=True, text=True, check=True)
    plan = json.loads(result.stdout)
    names = [phase['name'] for phase in plan]
    assert names.index('rust_dependencies') < names.index('rust_rebuild') < names.index('parser_language_update')
    assert names.index('dashboard_dependencies') < names.index('dashboard_rebuild') < names.index('plugin_package_rebuild')
    rust = next(p['argv'] for p in plan if p['name'] == 'rust_rebuild')
    assert '--offline' in rust and '--timings' in rust and '--release' in rust
    package = next(p['argv'] for p in plan if p['name'] == 'plugin_package_rebuild')
    assert '--prebuilt-rust' in package and '--prebuilt-dashboard' in package
    assert '--no-build' in next(p['argv'] for p in plan if p['name'] == 'native_analysis')
    assert names[-1] == 'host_model_analysis'
    assert not output.exists()


def test_codex_explicit_model_effort_and_standard_tier(tmp_path):
    argv = command(tmp_path / 'subject', tmp_path / 'plugin', tmp_path)
    assert argv[argv.index('--model') + 1] == 'gpt-6.1-sol'
    assert 'model_reasoning_effort="medium"' in argv
    assert 'service_tier="default"' in argv
    assert '--ignore-user-config' in argv
    assert '--json' in argv
    assert '--all --full' in argv[-1]
    assert 'preapproved' in argv[-1]


@pytest.mark.parametrize('settings', [
    {'concurrency': 0}, {'buildJobs': True}, {'sampleIntervalSeconds': 0.001},
    {'phaseTimeoutSeconds': float('nan')}, {'analysisCommand': []},
    {'analysisCommand': 'shell command'}, {'parserLanguages': [23]}, {'unknown': True},
])
def test_reject_invalid_configuration(tmp_path, settings):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        full_run.load_config(path)


@pytest.mark.skipif(sys.platform != 'linux' or not Path('/usr/bin/time').exists(), reason='Linux GNU time required')
def test_real_metrics_and_failure_exit(tmp_path):
    result = full_run.measure('allocation', [sys.executable, '-c',
        'import time; data=bytearray(32*1024*1024); time.sleep(.12)'],
        tmp_path, tmp_path, os.environ.copy(), 5, .02)
    assert result['status'] == 'ok'
    assert result['resources']['maxProcessRssKiB'] > 30000
    assert result['sampledPeakProcessGroupRssSumBytes'] > 32 * 1024 * 1024
    assert result['durationSeconds'] >= .12
    assert (tmp_path / 'allocation.samples.jsonl').is_file()
    result = full_run.measure('failure', [sys.executable, '-c', 'raise SystemExit(17)'],
                              tmp_path, tmp_path, os.environ.copy(), 5, .02)
    assert result['status'] == 'failed' and result['exitCode'] == 17


@pytest.mark.skipif(sys.platform != 'linux' or not Path('/usr/bin/time').exists(), reason='Linux GNU time required')
def test_timeout_retains_log_and_stops_process(tmp_path):
    result = full_run.measure('timeout', [sys.executable, '-c',
        'import os,time; print(os.getpid(),flush=True); time.sleep(20)'],
        tmp_path, tmp_path, os.environ.copy(), .15, .02)
    assert result['status'] == 'timeout'
    assert result['durationSeconds'] < 5
    assert (tmp_path / 'timeout.log').is_file()


def test_failure_writes_partial_report_and_stops_later_phases(tmp_path, monkeypatch):
    subject = tmp_path / 'subject'
    subject.mkdir()
    source = tmp_path / 'tool'
    source.mkdir()
    (source / 'source.txt').write_text('preserve')
    config = config_without_model(tmp_path)
    monkeypatch.setattr(full_run, 'ROOT', source)
    monkeypatch.setattr(full_run.shutil, 'which', lambda name: '/bin/true')
    monkeypatch.setattr(full_run, 'identity', lambda *args: 'fixture')
    calls = []
    def fail(name, *args):
        calls.append(name)
        return {'name': name, 'status': 'failed', 'exitCode': 42, 'durationSeconds': .1,
                'sampledPeakProcessGroupRssSumBytes': None, 'resources': None}
    monkeypatch.setattr(full_run, 'measure', fail)
    output = tmp_path / 'results'
    assert full_run.main([str(subject), '--output-dir', str(output), '--config', str(config)]) == 1
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == 'failed'
    assert calls == ['rust_dependencies']
    assert (output / 'workspace/source.txt').read_text() == 'preserve'
    assert (source / 'source.txt').read_text() == 'preserve'
    assert not list(subject.iterdir())
    assert (output / 'report.md').is_file()
    assert full_run.main([str(subject), '--output-dir', str(output), '--config', str(config)]) == 2


def test_package_prebuilt_inputs_do_not_rebuild(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('build_dist_fixture', ROOT / 'scripts/build_dist.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    binary = tmp_path / 'binary'
    binary.write_text('fixture')
    binary.chmod(0o755)
    packages = tmp_path / 'packages'
    (packages / 'dashboard/dist').mkdir(parents=True)
    (packages / 'dashboard/dist/index.html').write_text('dashboard')
    monkeypatch.setattr(builder, 'PKGS', packages)
    monkeypatch.setattr(builder, 'BUILD', tmp_path / 'build')
    monkeypatch.setattr(builder, 'DIST', tmp_path / 'dist')
    monkeypatch.setattr(builder, 'read_version', lambda: 'fixture')
    def unexpected():
        pytest.fail('packaging invoked a build or dependency install')
    monkeypatch.setattr(builder, 'build_rust', unexpected)
    monkeypatch.setattr(builder, 'build_dashboard', unexpected)
    seen = []
    monkeypatch.setattr(builder, 'assemble_payload', lambda payload, executable: seen.append(executable))
    monkeypatch.setattr(builder, 'make_archives', lambda *args, **kwargs: [])
    monkeypatch.setattr(sys, 'argv', ['build_dist.py', '--prebuilt-rust', str(binary), '--prebuilt-dashboard'])
    assert builder.main() == 0
    assert seen == [binary.resolve()]


def test_snapshot_digest_tracks_symlinks_and_rejects_escapes(tmp_path):
    snapshot = tmp_path / 'snapshot'
    snapshot.mkdir()
    (snapshot / 'a').write_text('same')
    (snapshot / 'b').write_text('same')
    link = snapshot / 'link'
    link.symlink_to('a')
    before = full_run.snapshot_digest(snapshot)
    # Replace only this test-created link; no source checkout mutation.
    replacement = snapshot / 'replacement'
    replacement.symlink_to('b')
    replacement.replace(link)
    assert full_run.snapshot_digest(snapshot) != before
    (snapshot / 'external').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='external symlink'):
        full_run.snapshot_digest(snapshot)


def test_codex_wrapper_records_emitted_usage_and_validates_graph(tmp_path, monkeypatch):
    from benchmark import codex_analysis
    subject = tmp_path / 'subject'
    subject.mkdir()
    plugin = tmp_path / 'plugin'
    (plugin / 'skills/understand').mkdir(parents=True)
    (plugin / 'skills/understand/SKILL.md').write_text('fixture skill')
    class Result:
        returncode = 0
    def run(argv, stdout):
        assert 'service_tier="default"' in argv
        stdout.write(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 123, 'output_tokens': 45}}) + '\n')
        (subject / '.ua').mkdir()
        (subject / '.ua/knowledge-graph.json').write_text('{"nodes": [], "edges": []}')
        return Result()
    monkeypatch.setattr(codex_analysis.subprocess, 'run', run)
    assert codex_analysis.main([str(subject), str(plugin), str(tmp_path)]) == 0
    usage = json.loads((tmp_path / 'codex-usage.json').read_text())
    assert usage['usageReportedByCli'] == {'input_tokens': 123, 'output_tokens': 45}
    assert usage['serviceTierRequested'] == 'default'
    assert (subject / '.agents/skills/understand').resolve() == plugin / 'skills/understand'


def test_snapshot_preserves_plugin_catalog_but_skips_local_installs_and_tools(tmp_path):
    source = tmp_path / 'source'
    (source / '.agents').mkdir(parents=True)
    (source / '.agents/installed').write_text('local runtime')
    (source / '.private').mkdir()
    (source / '.private/tool').write_text('local profiling tool')
    catalog = source / 'understand-anything-plugin/.agents/plugins'
    catalog.mkdir(parents=True)
    (catalog / 'marketplace.json').write_text('{"plugins": []}')
    snapshot = tmp_path / 'snapshot'
    shutil.copytree(source, snapshot, ignore=full_run.source_ignore)
    assert not (snapshot / '.agents').exists()
    assert not (snapshot / '.private').exists()
    assert (snapshot / 'understand-anything-plugin/.agents/plugins/marketplace.json').is_file()
