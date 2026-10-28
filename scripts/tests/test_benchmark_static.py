"""Saved-artifact reports need no engine, parsers, source checkout, or network."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from benchmark_static import main, summarize

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def artifacts(tmp_path):
    directory = tmp_path / 'repo with spaces' / '.ua'
    (directory / 'intermediate').mkdir(parents=True)
    (directory / 'knowledge-graph.json').write_text(json.dumps({
        'project': {'name': 'fixture'},
        'nodes': [{'id': 'a', 'type': 'file', 'filePath': 'a.py'},
                  {'id': 'b', 'type': 'function', 'filePath': 'a.py'},
                  {'id': 'c', 'type': 'file', 'filePath': 'other.py'},
                  {'id': 'c', 'type': 'file', 'filePath': 'other.py'}],
        'edges': [{'source': 'a', 'target': 'b', 'type': 'contains'},
                  {'source': 'a', 'target': 'absent', 'type': 'imports'}],
    }))
    (directory / 'intermediate/scan-result.json').write_text(json.dumps({
        'files': [{'path': 'a.py', 'language': 'Python', 'sizeLines': 100},
                  {'path': 'b.py', 'language': 'Python', 'sizeLines': 20}],
    }))
    return directory


def test_full_report_counts_distinct_paths_and_preserves_inputs(artifacts):
    before = {str(p): p.read_bytes() for p in artifacts.rglob('*') if p.is_file()}
    report = summarize(artifacts, 60, 'full')
    assert report['scan']['files'] == 2
    assert report['scan']['lines'] == 120
    assert report['scan']['filesByLanguage'] == {'Python': 2}
    assert report['scan']['filesWithoutGraphPath'] == 1
    assert report['graph']['distinctFilePaths'] == 2
    assert report['graph']['isolatedNodes'] == 1
    assert report['consistency'] == {'duplicateNodeIds': 1, 'danglingEdges': 1}
    assert report['throughput'] == {'filesPerMinute': 2, 'linesPerSecond': 2}
    assert before == {str(p): p.read_bytes() for p in artifacts.rglob('*') if p.is_file()}


@pytest.mark.parametrize('scope', ['unknown', 'incremental'])
def test_incremental_and_unknown_time_do_not_use_full_snapshot(artifacts, scope):
    report = summarize(artifacts, 60, scope)
    assert all(value is None for value in report['throughput'].values())


def test_graph_only_and_missing_line_counts_are_not_zero(artifacts, tmp_path):
    graph_only = tmp_path / 'graph-only'
    graph_only.mkdir()
    (graph_only / 'knowledge-graph.json').write_bytes((artifacts / 'knowledge-graph.json').read_bytes())
    assert summarize(graph_only, 60, 'full')['scan'] is None
    scan = artifacts / 'intermediate/scan-result.json'
    scan.write_text(json.dumps({'files': [{'path': 'a.py', 'language': 'Python'}]}))
    report = summarize(artifacts, 60, 'full')
    assert report['scan']['lines'] is None
    assert report['throughput']['linesPerSecond'] is None
    assert report['throughput']['filesPerMinute'] == 1


@pytest.mark.parametrize('seconds', ['0', '-1', 'nan', 'inf', 'invalid'])
def test_bad_time_is_an_actionable_cli_error(artifacts, seconds, capsys):
    assert main([str(artifacts), '--total-seconds', seconds]) == 2
    assert 'Cannot summarize saved analysis:' in capsys.readouterr().err


def test_malformed_optional_artifact_is_not_silently_ignored(artifacts, capsys):
    (artifacts / 'meta.json').write_text('{broken')
    assert main([str(artifacts)]) == 2
    assert 'Cannot summarize' in capsys.readouterr().err


def test_make_json_target_handles_literal_paths_and_no_build(artifacts):
    result = subprocess.run(['make', '--no-print-directory', 'benchmark-static',
                             f'UA_DIR={artifacts}', 'TOTAL_SECONDS=120',
                             'TIME_SCOPE=full', 'FORMAT=json'], cwd=ROOT,
                            text=True, capture_output=True, check=True)
    report = json.loads(result.stdout)
    assert report['timing']['source'] == 'user-supplied'
    assert report['throughput']['filesPerMinute'] == 1
