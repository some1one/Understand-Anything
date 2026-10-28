"""Valgrind profiles remain distinct from ordinary benchmark timing reports."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from benchmark import full_run, profile_native


def test_separate_profiling_build_and_optional_tools(tmp_path):
    config = full_run.load_config(full_run.DEFAULT_CONFIG)
    plan = full_run.phases(tmp_path / 'workspace', tmp_path / 'run', tmp_path / 'subject', config)
    names = [name for name, _, _ in plan]
    assert names.index('native_analysis') < names.index('rust_profiling_rebuild') < names.index('valgrind_callgrind')
    rebuild = next(argv for name, argv, _ in plan if name == 'rust_profiling_rebuild')
    assert 'profile.release.debug=2' in rebuild
    assert 'profile.release.strip="none"' in rebuild
    assert any('dwarf-version=4' in arg for arg in rebuild)
    assert any('target-valgrind' in arg for arg in rebuild)
    config['valgrindTools'] = []
    assert not any('valgrind' in name or 'profiling' in name for name, _, _ in
                   full_run.phases(tmp_path / 'workspace', tmp_path / 'run', tmp_path / 'subject', config))


@pytest.mark.parametrize('value', [['bad'], ['callgrind', 'callgrind'], 'massif', [None]])
def test_invalid_tool_configuration(tmp_path, value):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'valgrindTools': value}))
    with pytest.raises(ValueError, match='valgrindTools'):
        full_run.load_config(config)


def test_callgrind_events_and_massif_same_snapshot_peak(tmp_path):
    callgrind = tmp_path / 'scan.123.callgrind'
    callgrind.write_text('events: Ir Dr Dw\nsummary: 100 20 10\n')
    report = profile_native.summarize_profiles('callgrind', tmp_path)
    assert report['summedEvents'] == {'Ir': 100, 'Dr': 20, 'Dw': 10}
    assert report['processProfiles'] == 1
    massif = tmp_path / 'scan.123.massif'
    massif.write_text('snapshot=0\nmem_heap_B=100\nmem_heap_extra_B=8\nmem_stacks_B=0\n'
                      'snapshot=1\nmem_heap_B=10\nmem_heap_extra_B=8\nmem_stacks_B=200\n')
    report = profile_native.summarize_profiles('massif', tmp_path)
    assert report['largestProcessPeakHeapAndStackBytes'] == 218
    assert report['profiles'][0]['peakSnapshot']['snapshot'] == 1


def test_memcheck_error_records_and_occurrences_are_distinct(tmp_path):
    path = tmp_path / 'scan.123.xml'
    path.write_text('''<valgrindoutput>
<error><unique>0x1</unique><kind>InvalidRead</kind></error>
<error><unique>0x2</unique><kind>Leak_DefinitelyLost</kind><xwhat><leakedbytes>64</leakedbytes></xwhat></error>
<errorcounts><pair><unique>0x1</unique><count>3</count></pair></errorcounts>
<status><state>FINISHED</state></status></valgrindoutput>''')
    report = profile_native.summarize_profiles('memcheck', tmp_path)
    assert report['errorRecords'] == 2
    assert report['reportedOccurrences'] == 3
    assert report['definitelyOrIndirectlyLostBytes'] == 64


def test_truncated_profiles_are_not_reported_as_success(tmp_path):
    (tmp_path / 'scan.123.xml').write_text('<valgrindoutput>')
    report = profile_native.summarize_profiles('memcheck', tmp_path)
    assert report['profileReadErrors'] and report['processProfiles'] == 0
    (tmp_path / 'scan.123.callgrind').write_text('events: Ir Dr\nsummary: 123\n')
    assert profile_native.summarize_profiles('callgrind', tmp_path)['profileReadErrors']


@pytest.fixture(scope='module')
def valgrind_fixture(tmp_path_factory):
    if not full_run.find_valgrind() or not shutil.which('cc'):
        pytest.skip('Valgrind and a C compiler are required for the opt-in real-tool fixture')
    directory = tmp_path_factory.mktemp('real-valgrind')
    source = directory / 'allocation.c'
    source.write_text('''#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
int main(int argc, char **argv) {
    volatile char *p = malloc(65536);
    if (!p) return 1;
    for (int i=0; i<65536; i++) p[i] = (char)i;
    free((void*)p);
    if (argc > 1 && strcmp(argv[1], "fork") == 0) {
        pid_t child = fork();
        if (child == 0) { execl("/usr/bin/true", "true", (char*)0); _exit(1); }
        waitpid(child, 0, 0);
    } else if (argc > 1) p[0] = 3;
    return 0;
}
''')
    binary = directory / 'allocation'
    subprocess.run(['cc', '-g', '-gdwarf-4', '-O0', str(source), '-o', str(binary)], check=True)
    return binary


@pytest.mark.parametrize('tool', ['callgrind', 'massif', 'memcheck'])
def test_real_valgrind_profiles(tool, valgrind_fixture, tmp_path):
    command = [arg.replace('{worker}', 'fixture') for arg in profile_native.valgrind_prefix(tool, tmp_path)]
    subprocess.run([*command, str(valgrind_fixture)], check=True, capture_output=True, timeout=60)
    report = profile_native.summarize_profiles(tool, tmp_path)
    assert not report['profileReadErrors']
    assert report['processProfiles'] == 1
    if tool == 'callgrind':
        assert report['summedEvents']['Ir'] > 0
    elif tool == 'massif':
        assert report['largestProcessPeakHeapAndStackBytes'] >= 65536
    else:
        assert report['errorRecords'] == 0


def test_real_memcheck_reports_memory_error_and_nonzero_exit(valgrind_fixture, tmp_path):
    command = [arg.replace('{worker}', 'fixture') for arg in profile_native.valgrind_prefix('memcheck', tmp_path)]
    result = subprocess.run([*command, str(valgrind_fixture), 'use-after-free'], capture_output=True, timeout=60)
    assert result.returncode == 97
    report = profile_native.summarize_profiles('memcheck', tmp_path)
    assert report['errorRecords'] >= 1
    assert report['profiles'][0]['errorsByKind']['InvalidWrite'] == 1


def test_real_memcheck_fork_exec_preserves_parent_xml(valgrind_fixture, tmp_path):
    command = [arg.replace('{worker}', 'fixture') for arg in profile_native.valgrind_prefix('memcheck', tmp_path)]
    subprocess.run([*command, str(valgrind_fixture), 'fork'], capture_output=True, timeout=60, check=True)
    report = profile_native.summarize_profiles('memcheck', tmp_path)
    assert not report['profileReadErrors']
    assert report['processProfiles'] == 1
    assert report['errorRecords'] == 0


def test_semantic_comparison_requires_present_matching_digests():
    baseline = {'determinism': {'inputDigest': 'same', 'outputDigest': 'original'}}
    assert profile_native.compare_semantics(baseline, baseline) == {'inputDigest': True, 'outputDigest': True}
    changed = {'determinism': {'inputDigest': 'same', 'outputDigest': 'changed'}}
    assert profile_native.compare_semantics(baseline, changed)['outputDigest'] is False
    assert profile_native.compare_semantics(baseline, {}) == {'inputDigest': None, 'outputDigest': None}


def test_pipeline_prefix_wraps_native_worker_with_unique_name(tmp_path, monkeypatch):
    import threading
    from benchmark import pipeline
    from benchmark.contract import new_report
    from benchmark.runner import StageError, unstarted_metric
    seen = []
    def fail(command, *args):
        seen.append(command)
        raise StageError('fixture-failure', unstarted_metric('fixture-failure'))
    monkeypatch.setattr(pipeline, 'worker', fail)
    report = new_report()
    pipeline.run(report, tmp_path, tmp_path, tmp_path / 'engine', tmp_path / 'cache', threading.Event(),
                 command_prefix=['valgrind', '--log-file=profile.{worker}.%p.log'])
    assert seen[0][:3] == ['valgrind', '--log-file=profile.scan.%p.log', str(tmp_path / 'engine')]
    assert report['error'] == 'fixture-failure'
