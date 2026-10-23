"""Small offline contracts for the opt-in native benchmark."""
import json
from pathlib import Path
import sys

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from benchmark.contract import digest, new_report

SCHEMA = json.loads((ROOT / 'docs/benchmarks/large-repo-report-2.0.0.schema.json').read_text())


def validate(report):
    jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(report)


def test_partial_failure_contract():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    validate(new_report())
    report = new_report()
    report['status'] = 'ok'
    with pytest.raises(jsonschema.ValidationError):
        validate(report)


def test_semantic_digest_uses_canonical_json():
    assert digest({'a': 1, 'b': 2}) == digest({'b': 2, 'a': 1})
    assert digest({'a': 1}) != digest({'a': 2})


def test_worker_measures_isolated_process_and_failure(tmp_path):
    from benchmark.runner import StageError, worker
    import threading
    metric = worker([sys.executable, '-c', 'sum(range(100000))'], tmp_path, 'ok', threading.Event())
    assert metric['status'] == 'ok'
    assert metric['maxWorkerPeakRssBytes'] > 0
    assert metric['userCpuTimeMicros'] >= 0
    with pytest.raises(StageError) as error:
        worker([sys.executable, '-c', 'raise SystemExit(7)'], tmp_path, 'bad', threading.Event())
    assert error.value.metric['status'] == 'failed'


def test_worker_cancellation_and_timeout(tmp_path):
    from benchmark.runner import StageError, worker
    import threading
    stop = threading.Event()
    stop.set()
    with pytest.raises(StageError, match='cancelled'):
        worker([sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path, 'cancel', stop)
    with pytest.raises(StageError, match='worker-timeout'):
        worker([sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path, 'timeout', threading.Event(), timeout=.03)


def test_run_warnings_are_bounded_and_worker_cpu_is_summed():
    from benchmark.pipeline import warn, combined_metrics
    report = new_report()
    for stage in ('scan', 'imports', 'batching', 'structure'):
        for code in ('worker-warning', 'invalid-output'):
            warn(report, stage, code, 3)
    assert len(report['warnings']) == 5
    assert report['warningCount'] == 24
    assert report['warningsTruncated']
    one = dict(status='ok', userCpuTimeMicros=10, systemCpuTimeMicros=2,
               maxWorkerPeakRssBytes=1024, outputBytes=10, error=None, workers=1)
    two = {**one, 'userCpuTimeMicros': 30, 'maxWorkerPeakRssBytes': 2048}
    metric = combined_metrics([one, two], 100)
    assert metric['userCpuTimeMicros'] == 40
    assert metric['systemCpuTimeMicros'] == 4
    assert metric['maxWorkerPeakRssBytes'] == 2048
    assert metric['aggregatePeakRssBytes'] is None
