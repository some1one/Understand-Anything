import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from benchmark import cli
from benchmark.delivery import read_pair
from benchmark.isolation import hash_file
from benchmark.runner import RUST
from test_benchmark import validate

SCRIPT = Path(__file__).resolve().parents[1] / 'benchmark_large_repo.py'


@pytest.fixture(scope='module')
def engine():
    subprocess.run(['cargo', '+stable', 'build', '--offline', '--locked'], cwd=RUST, check=True, capture_output=True)
    return RUST / 'target/debug/understand-anything-rs'


@pytest.fixture
def args(tmp_path, engine):
    cache = tmp_path / 'cache'
    libs = cache / 'tree-sitter-language-pack/v1.20.0/libs'
    libs.mkdir(parents=True)
    # No supported grammar is needed for Markdown or unknown extensions. Dummy
    # asset makes preconfiguration explicit; no parser load can use it.
    (libs / 'fixture.identity').write_text('not a grammar')
    subject = tmp_path / 'subject'
    subject.mkdir()
    output = tmp_path / 'report.json'
    return [str(subject), '--output', str(output), '--parser-cache-dir', str(cache), '--no-build', '--build-mode', 'debug']


def test_cli_success_public_report_and_git_immutability(tmp_path, args):
    subject = Path(args[0])
    subprocess.run(['git', 'init', '-q', str(subject)], check=True)
    (subject / 'README.md').write_text('# fixture with private source marker\n')
    subprocess.run(['git', '-C', str(subject), 'add', 'README.md'], check=True)
    before_status = subprocess.check_output(['git', '-C', str(subject), 'status', '--porcelain=v1', '-z'])
    before_hash = hash_file(subject / 'README.md')
    before_index = hash_file(subject / '.git/index')
    assert cli.main(args) == 0
    report = read_pair(tmp_path / 'report.json')
    validate(report)
    assert report['status'] == 'degraded'  # optional call graph unsupported
    assert report['coverage']['structureSucceeded'] == 1
    assert report['configuration']['ignoreRules']['gitEnumeration']
    assert before_status == subprocess.check_output(['git', '-C', str(subject), 'status', '--porcelain=v1', '-z'])
    assert before_hash == hash_file(subject / 'README.md')
    assert before_index == hash_file(subject / '.git/index')
    for path in (tmp_path / 'report.json', tmp_path / 'report.md'):
        text = path.read_text()
        assert str(tmp_path) not in text
        assert 'private source marker' not in text
        assert 'hostname' not in text
    assert cli.main(['--check-pair', str(tmp_path / 'report.json')]) == 0


def test_cleanup_failure_preserves_primary_error(tmp_path, args, monkeypatch):
    def fail(report, *rest):
        report.update(status='failed', error='worker-exit')
    def cleanup_error(directory):
        raise OSError('sensitive path /private/user')
    monkeypatch.setattr(cli, 'run', fail)
    monkeypatch.setattr(cli, 'cleanup', cleanup_error)
    assert cli.main(args) == 1
    report = read_pair(tmp_path / 'report.json')
    validate(report)
    assert report['error'] == 'worker-exit'
    assert report['secondaryErrors'] == ['cleanup-failed']


def test_keep_artifacts_and_cancellation(tmp_path, args, monkeypatch, capsys):
    from benchmark.runner import worker
    def slow(report, subject, directory, binary, cache, stop, timeout):
        worker([sys.executable, '-c', 'import time; time.sleep(60)'], directory, 'slow', stop)
    monkeypatch.setattr(cli, 'run', slow)
    # Deliver SIGTERM only after the subprocess has started, rather than racing
    # startup/handlers. Using a timer here does not start an analysis worker.
    def cancel():
        os.kill(os.getpid(), signal.SIGTERM)
    timer = threading.Timer(.2, cancel)
    timer.start()
    try:
        # worker raises StageError; production pipeline normally captures it.
        from benchmark.runner import StageError
        original = cli.run
        def captured(report, *rest):
            try:
                original(report, *rest)
            except StageError as error:
                report.update(status='failed', error=error.code)
        monkeypatch.setattr(cli, 'run', captured)
        assert cli.main(args + ['--keep-artifacts']) == 130
    finally:
        timer.join()
    report = read_pair(tmp_path / 'report.json')
    validate(report)
    assert report['error'] == 'cancelled'
    stderr = capsys.readouterr().err
    location = stderr.split('diagnostics): ', 1)[1].splitlines()[0]
    assert Path(location).is_dir()


def test_cli_rejects_inside_output_and_invalid_concurrency(tmp_path, args):
    args[2] = str(Path(args[0]) / 'report.json')
    assert cli.main(args) == 2
    assert not (Path(args[0]) / 'report.json').exists()
    with pytest.raises(SystemExit) as error:
        cli.main(args + ['--concurrency', '33'])
    assert error.value.code == 2


def test_make_target_preserves_literal_paths(tmp_path):
    import shlex
    helper = tmp_path / 'spy.py'
    helper.write_text('import json, os, sys\nfrom pathlib import Path\nPath(os.environ["BENCHMARK_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))\n')
    subject = '/tmp/subject spaces $(do_not_expand) ; literal'
    output = '/tmp/report spaces $(do_not_expand).benchmark.json'
    cache = '/tmp/cache spaces $(do_not_expand)'
    capture = tmp_path / 'args.json'
    result = subprocess.run(['make', '--no-print-directory', 'benchmark-large-repo',
        'PYTHON=' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(helper)),
        'BENCHMARK_SUBJECT=' + subject, 'BENCHMARK_OUTPUT=' + output,
        'BENCHMARK_PARSER_CACHE=' + cache], cwd=SCRIPT.parents[1],
        env={**os.environ, 'BENCHMARK_CAPTURE': str(capture)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(capture.read_text()) == ['scripts/benchmark_large_repo.py', subject, '--output', output, '--parser-cache-dir', cache]
