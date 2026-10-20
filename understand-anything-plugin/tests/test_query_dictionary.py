"""Graph-first filtering and cache-only technical dictionary regressions."""
import hashlib
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/understand-chat/scripts'
sys.path.insert(0, str(SCRIPTS))
from query_graph import build_payload
from query_dictionary import cached_words


def fixture_cache(tmp_path, graph, words):
    graph_path = tmp_path / 'knowledge-graph.json'
    raw = json.dumps(graph).encode()
    graph_path.write_bytes(raw)
    directory = tmp_path / 'query-dictionaries'
    directory.mkdir()
    data = json.dumps(words).encode()
    digest = hashlib.sha256(data).hexdigest()
    filename = f'python-{digest}.json'
    (directory / filename).write_bytes(data)
    import gzip
    source = SCRIPTS.parents[2] / 'packages/rust/tests/fixtures/dictionaries'
    generation = json.loads((source / 'current.json').read_text())['generation']
    lemma_bytes = gzip.decompress((source / generation / 'lemmas.json.gz').read_bytes()).strip()
    manifest = {'version': 3, 'lemmaSha256': hashlib.sha256(lemma_bytes).hexdigest(), 'graphSha256': hashlib.sha256(raw).hexdigest(),
                'dictionaries': {'python': {'file': filename, 'sha256': digest}}}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return graph_path, raw, directory, filename


def test_graph_names_survive_inside_questions_before_limit():
    nodes = [{'id': f'post:{i}', 'name': 'POST', 'summary': 'Handles requests.'} for i in range(30)]
    get = {'id': 'get-handler', 'name': 'GET', 'summary': 'Handles requests.'}
    graph = {'nodes': [*nodes, get]}
    for question in ['GET requests', 'Where are GET requests handled?', 'get requests']:
        assert build_payload(graph, question)['matchedNodes'] == [get]
    named = {'id': 'symbol', 'name': 'beautiful', 'summary': 'Handles requests.'}
    assert build_payload({'nodes': [*nodes, named]}, 'beautiful requests')['matchedNodes'] == [named]


def test_cached_acronym_is_preserved_but_conversational_get_is_filtered(tmp_path):
    nodes = [{'id': f'post:{i}', 'name': f'Handler{i}', 'summary': 'POST requests'} for i in range(30)]
    get = {'id': 'target', 'name': 'ReadHandler', 'summary': 'GET requests'}
    graph = {'nodes': [*nodes, get]}
    path, raw, directory, filename = fixture_cache(tmp_path, graph, ['GET', 'get', 'readonly'])
    # Unreferenced dictionaries from old language selections must not be loaded.
    (directory / 'rust-old.json').write_text('["unrelated"]')
    words = cached_words(path, raw)
    assert words == {'GET', 'get', 'readonly'}
    assert build_payload(graph, 'GET requests', words)['matchedNodes'] == [get]
    # Lowercase conversational scaffolding must not become a required term.
    auth = {'id': 'auth', 'summary': 'authentication'}
    assert build_payload({'nodes': [auth]}, 'get authentication', words)['matchedNodes'] == [auth]


def test_cache_unavailable_never_loads_full_dictionary(tmp_path, capsys):
    path, raw, directory, filename = fixture_cache(tmp_path, {}, ['GET'])
    assert cached_words(path, raw) == {'GET'}
    assert cached_words(path, b'{"nodes": []}') == set()
    assert 'does not match' in capsys.readouterr().err
    (directory / filename).write_text('[]')
    assert cached_words(path, raw) == set()
    assert 'checksum mismatch' in capsys.readouterr().err
    (directory / 'manifest.json').write_text('{')
    assert cached_words(path, raw) == set()
    assert 'using graph names only' in capsys.readouterr().err


def test_vendor_checksum_and_license_coverage():
    import gzip
    directory = Path(__file__).resolve().parents[1] / 'packages/rust/tests/fixtures/dictionaries'
    pointer = json.loads((directory / 'current.json').read_text())
    vendor = directory / pointer['generation']
    manifest = json.loads((vendor / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest
    words = json.loads(gzip.decompress((vendor / 'cspell.json.gz').read_bytes()))
    for name, entries in words.items():
        assert entries == sorted(set(entries))
        assert 'MIT License' in (vendor / f'cspell-{name}.LICENSE').read_text()
