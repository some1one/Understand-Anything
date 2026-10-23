"""Actual Rust commands on tiny repositories; never clone or fetch assets."""
import json
from pathlib import Path
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from benchmark.contract import new_report
from benchmark.pipeline import run
from benchmark.runner import RUST
from test_benchmark import validate


@pytest.fixture(scope='module')
def engine():
    subprocess.run(['cargo', '+stable', 'build', '--offline', '--locked'], cwd=RUST, check=True, capture_output=True)
    return RUST / 'target/debug/understand-anything-rs'


@pytest.fixture
def cache():
    value = os.environ.get('UA_TEST_PARSER_CACHE')
    if not value:
        pytest.skip('set UA_TEST_PARSER_CACHE to preconfigured 1.20.0 grammars for multilingual checks')
    return Path(value)


def execute(tmp_path, engine, cache, contents):
    subject = tmp_path / 'subject'
    subject.mkdir(exist_ok=True)
    for path, text in contents.items():
        destination = subject / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    report = new_report()
    report['configuration']['concurrency'] = 2
    run(report, subject, artifacts, engine, cache, threading.Event())
    validate(report)
    return report


def test_empty_and_unsupported(tmp_path, engine):
    report = execute(tmp_path, engine, tmp_path / 'missing-cache', {})
    assert report['status'] == 'ok', report
    assert report['coverage']['files'] == 0
    assert report['stages']['structure']['workers'] == 0
    report = execute(tmp_path, engine, tmp_path / 'missing-cache', {'file.unrecognized': 'anything'})
    assert report['status'] == 'degraded', report
    assert report['coverage']['structureUnsupported'] == 1
    assert report['coverage']['structureSucceeded'] == 0


def test_multilingual_semantics_and_exclusions(tmp_path, engine, cache):
    contents = {'a.py': 'def hello():\n    return 1\n', 'b.rs': 'fn work() {}\n',
                'c.ts': 'export function test() { return 2; }\n',
                '.ua/private.py': 'invalid data', '.understand-anything/private.rs': 'invalid',
                'old.benchmark.json': 'invalid', 'old.benchmark.md': 'invalid'}
    report = execute(tmp_path, engine, cache, contents)
    assert report['status'] == 'ok', report
    assert report['coverage']['files'] == report['coverage']['structureSucceeded'] == 3
    first = report['determinism']
    report = execute(tmp_path, engine, cache, contents)
    assert report['determinism'] == first
    assert {p.relative_to(tmp_path / 'subject').as_posix(): p.read_text() for p in (tmp_path / 'subject').rglob('*') if p.is_file()} == contents


def test_malformed_supported_source_fails(tmp_path, engine, cache):
    report = execute(tmp_path, engine, cache, {'broken.py': 'def broken(:\n'})
    assert report['status'] == 'failed'
    assert report['error'] == 'parse-failed'
    assert report['coverage']['parseFailed'] == 1
    assert report['coverage']['structureSucceeded'] == 0


def test_missing_advertised_parser_fails_without_download(tmp_path, engine):
    report = execute(tmp_path, engine, tmp_path / 'missing-cache', {'a.py': 'def hello():\n    pass\n'})
    assert report['status'] == 'failed'
    assert report['stages']['imports']['status'] == 'failed'
    assert not (tmp_path / 'missing-cache').exists()


def test_unreadable_input_is_failed(tmp_path, engine):
    subject = tmp_path / 'subject'
    subject.mkdir()
    # Invalid UTF-8 is readable by the byte scanner but unreadable by parsers,
    # and exercises actual EILSEQ regardless of the test user's permissions.
    (subject / 'bad.py').write_bytes(b'\xff\xfe')
    report = execute(tmp_path, engine, tmp_path / 'missing-cache', {})
    assert report['status'] == 'failed'
    assert report['coverage']['unreadable'] == 1


@pytest.mark.parametrize('failure', ['exit', 'invalid', 'exception'])
def test_simulated_structure_worker_failures(tmp_path, engine, monkeypatch, failure):
    import benchmark.pipeline as pipeline
    from benchmark.runner import StageError
    original = pipeline.worker

    def injected(command, directory, name, stop, timeout):
        if name.startswith('structure-'):
            if failure == 'exception':
                raise OSError('private path /never/publish')
            if failure == 'exit':
                metric = original([sys.executable, '-c', 'raise SystemExit(7)'], directory, name, stop, timeout)
                return metric
            metric = original([sys.executable, '-c', 'pass'], directory, name, stop, timeout)
            (directory / (name + '.json')).write_text('{"scriptCompleted":true,"coverage":[],"results":[]}')
            return metric
        return original(command, directory, name, stop, timeout)
    monkeypatch.setattr(pipeline, 'worker', injected)
    report = execute(tmp_path, engine, tmp_path / 'missing-cache', {'README.md': '# Heading'})
    assert report['status'] == 'failed'
    assert '/never/publish' not in json.dumps(report)
    assert report['error'] in ('worker-exit', 'invalid-output')
