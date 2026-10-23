import json
import multiprocessing
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from benchmark.contract import new_report
from benchmark.delivery import DeliveryError, publish, read_pair


def test_report_pairs_and_mismatch(tmp_path):
    output = tmp_path / 'report.json'
    report = new_report()
    publish(report, output, tmp_path / 'subject')
    assert read_pair(output) == report
    output.with_suffix('.md').write_text('pairId: 0000\n')
    with pytest.raises(ValueError, match='report-pair-mismatch'):
        read_pair(output)


@pytest.mark.parametrize('prior', [False, True])
def test_second_replacement_failure_restores_prior_pair(tmp_path, monkeypatch, prior):
    import benchmark.delivery as delivery
    output = tmp_path / 'report.json'
    if prior:
        publish(new_report(), output, tmp_path / 'subject')
    before = {p: p.read_bytes() for p in (output, output.with_suffix('.md')) if p.exists()}
    original = delivery.os.replace
    count = 0
    def fail_second(source, destination):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError('private diagnostics /never/publish')
        return original(source, destination)
    monkeypatch.setattr(delivery.os, 'replace', fail_second)
    with pytest.raises(DeliveryError) as error:
        publish(new_report(), output, tmp_path / 'subject')
    assert error.value.rollback_failures == 0
    assert {p: p.read_bytes() for p in (output, output.with_suffix('.md')) if p.exists()} == before
    assert not list(tmp_path.glob('.report.*'))


def writer(output, subject, count):
    for _ in range(count):
        publish(new_report(), output, subject)
        read_pair(output)


def test_concurrent_writers_serialize_pairs(tmp_path):
    output = tmp_path / 'report.json'
    processes = [multiprocessing.get_context("fork").Process(target=writer, args=(output, tmp_path / 'subject', 10)) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert read_pair(output)['status'] == 'failed'


def test_output_write_failure_preserves_pair(tmp_path, monkeypatch):
    import benchmark.delivery as delivery
    output = tmp_path / 'report.json'
    report = new_report()
    publish(report, output, tmp_path / 'subject')
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(delivery, 'staged', fail)
    with pytest.raises(DeliveryError):
        publish(new_report(), output, tmp_path / 'subject')
    assert read_pair(output) == report
