"""Regression fixtures for query bounds, traversal, and changed-path helpers."""
import importlib.util
import json
from pathlib import Path
import subprocess

PLUGIN = Path(__file__).resolve().parents[1]


def module(skill, script):
    path = PLUGIN / 'skills' / skill / 'scripts' / f'{script}.py'
    spec = importlib.util.spec_from_file_location(script, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_query_complete_budget_and_supported_relationships(tmp_path, capfd):
    query = module('understand-chat', 'query_graph')
    nodes = [{'id': f'file:{i}.py', 'name': 'needle' if i == 0 else 'neighbor',
              'summary': '文' * 10000} for i in range(100)]
    graph = {'project': {'description': '文' * 100000, 'extension': ['x' * 9000] * 200},
             'nodes': nodes,
             'edges': [{'source': nodes[0]['id'], 'target': n['id'], 'type': 'imports'} for n in nodes[1:]],
             'layers': [{'id': 'all', 'name': 'All', 'nodeIds': [f'file:{i}.py' for i in range(20001)]}]}
    folder = tmp_path / '.understand-anything'
    folder.mkdir()
    (folder / 'knowledge-graph.json').write_text(json.dumps(graph))
    assert query.main([str(tmp_path), 'needle']) == 0
    output = capfd.readouterr().out
    assert len(output.encode('utf-8')) <= query.MAX_PAYLOAD_BYTES
    result = json.loads(output)
    assert result['matchedNodes'][0]['id'] == 'file:0.py'
    selected = {n['id'] for k in ('matchedNodes', 'connectedNodes') for n in result[k]}
    assert all(e['source'] in selected and e['target'] in selected for e in result['edges'])
    assert result['layers'][0]['totalMembers'] == 20001
    assert set(result['layers'][0]['nodeIds']) <= selected
    assert result['truncation']['textShortened']
    assert result['truncation']['omittedConnectedNodes'] > 0
    # Oversized identity and query still cannot escape the complete bound.
    graph['nodes'] = [{'id': 'x' * 100000, 'summary': '文' * 100000}]
    result = query.build_payload(graph, '文' * 50000)
    assert len(query.serialize(result).encode()) <= query.MAX_PAYLOAD_BYTES


def test_shallow_tree_prunes_before_descent(tmp_path, monkeypatch):
    context = module('understand', 'capture_project_context')
    for directory in ('.git', 'node_modules', 'dist', 'a/deep', 'b'):
        (tmp_path / directory).mkdir(parents=True)
        (tmp_path / directory / 'hidden.txt').write_text('x')
    (tmp_path / 'a' / 'visible.txt').write_text('x')
    (tmp_path / 'z.txt').write_text('x')
    (tmp_path / 'external').symlink_to(tmp_path / 'b', target_is_directory=True)
    (tmp_path / 'linked.txt').symlink_to(tmp_path / 'z.txt')
    assert context._dir_tree(tmp_path) == ['a/visible.txt', 'b/hidden.txt', 'z.txt']
    for i in range(150):
        (tmp_path / 'a' / f'{i:03}.txt').write_text('x')
    assert context._dir_tree(tmp_path) == [f'a/{i:03}.txt' for i in range(100)]


def test_rename_helpers_preserve_both_paths_and_unusual_names(tmp_path, capsys):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path).decode().strip()
    git('init', '-q')
    git('config', 'user.email', 'fixture@example.test')
    git('config', 'user.name', 'Fixture')
    old = 'a/ 文\r\nfile.py'
    new = 'b/ 文\r\nfile.py'
    (tmp_path / 'a').mkdir()
    (tmp_path / old).write_text('x = 1\n')
    git('add', '.')
    git('commit', '-qm', 'before')
    previous = git('rev-parse', 'HEAD')
    (tmp_path / 'b').mkdir()
    git('mv', old, new)
    git('commit', '-qm', 'rename')
    assert git('diff', '--name-status', previous, 'HEAD').startswith('R100')
    collector = module('understand', 'write_changed_files')
    assert collector.main([str(tmp_path), previous]) == 0
    changed = tmp_path / '.ua/tmp/changed-files.txt'
    assert set(changed.read_bytes().decode().split('\0')) == {old, new, ''}
    diff = module('understand-diff', 'diff_context')
    assert set(diff.changed_files(tmp_path, previous)[0]) == {old, new}
    graph = {'nodes': [{'id': 'old', 'filePath': old}, {'id': 'keep', 'filePath': 'keep.py'}],
             'edges': [{'source': 'old', 'target': 'keep'}]}
    (tmp_path / '.ua/knowledge-graph.json').write_text(json.dumps(graph))
    assert module('understand', 'prune_incremental_batch').main([str(tmp_path), str(changed)]) == 0
    pruned = json.loads((tmp_path / '.ua/intermediate/batch-existing.json').read_text())
    assert pruned == {'nodes': [graph['nodes'][1]], 'edges': []}


def test_dictionary_normalization_filters_filler_before_result_limit():
    query = module('understand-chat', 'query_graph')
    noise = [{'id': f'noise:{i}', 'name': f'Item {i}', 'summary': 'This is a really beautiful example.'}
             for i in range(30)]
    auth = {'id': 'file:auth.py', 'name': 'Authentication', 'summary': 'Handles authentication requests.'}
    graph = {'nodes': [*noise, auth]}
    for question in ['Where is authentication handled?', 'Please quickly explain this beautiful authentication.',
                     'AUTHENTICATION HANDLED?!', 'THIS BEAUTIFUL AUTHENTICATION HANDLED?!', 'Where are authentication requests handled?']:
        assert query.build_payload(graph, question)['matchedNodes'] == [auth]
    assert query.build_payload(graph, 'this is really beautiful')['matchedNodes'] == []
    assert query.build_payload(graph, '')['matchedNodes'] == []


def test_dictionary_inflections_boundaries_identifiers_and_graph_order():
    query = module('understand-chat', 'query_graph')
    nodes = [
        {'id': 'a', 'summary': 'Workers ran checks and handled requests.'},
        {'id': 'b', 'summary': 'A worker runs a check and handles a request.'},
        {'id': 'c', 'summary': 'Preauthentication and subrequests.'},
        {'id': 'd', 'name': 'OAuthHandler', 'filePath': 'src/auth_checks.py', 'tags': ['JWT'], 'summary': 'Quuxly processes callbacks.'},
        {'id': 'e', 'name': 'this', 'summary': 'Keyword definition.'},
        {'id': 'f', 'name': 'beautiful', 'summary': 'A symbol whose name is an adjective.'},
    ]
    result = query.build_payload({'nodes': nodes}, 'workers running checks handle requests')
    assert [n['id'] for n in result['matchedNodes']] == ['a', 'b']
    assert query.build_payload({'nodes': nodes}, 'authentication')['matchedNodes'] == []
    for term in ['OAuthHandler', 'src/auth_checks.py', 'JWT', 'Quuxly', 'oauth handler']:
        assert query.build_payload({'nodes': nodes}, term)['matchedNodes'] == [nodes[3]]
    for term, index in [('this', 4), ('`this`', 4), ('beautiful', 5), ('`beautiful`', 5)]:
        assert query.build_payload({'nodes': nodes}, term)['matchedNodes'] == [nodes[index]]


def test_dictionary_preserves_technical_modifiers_and_negation():
    module('understand-chat', 'query_graph')  # Add the packaged helper directory.
    query_terms = module('understand-chat', 'query_terms')
    terms = query_terms.query_terms("This really beautiful private handler isn't authenticated and runs asynchronously.")
    words = set().union(*terms)
    assert {'private', 'not', 'authenticate', 'asynchronously', 'run'} <= words
    assert not {'this', 'really', 'beautiful', 'is', 'and'}.intersection(words)
    # Dictionary POS, not an -ly suffix rule: an unknown technical name survives.
    assert query_terms.query_terms('quuxly') == [frozenset(['quuxly'])]


def test_packaged_dictionary_works_without_site_packages_and_fails_clearly_if_missing(tmp_path):
    import hashlib
    import sys
    builder_path = PLUGIN.parent / 'scripts/build_dist.py'
    spec = importlib.util.spec_from_file_location('query_packaging_fixture', builder_path)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    import os
    binary = Path(os.environ.get('UA_ENGINE_BINARY', str(PLUGIN / 'packages/rust/target/debug/understand-anything-rs')))
    assert binary.is_file(), 'Build the native engine before the packaging regression'
    payload = tmp_path / 'payload'
    builder.assemble_payload(payload, binary)
    dictionaries = payload / 'packages/rust/dictionaries'
    assert not dictionaries.exists(), 'Distribution bundles must exclude dictionary data'
    import shutil
    shutil.copytree(PLUGIN / 'packages/rust/tests/fixtures/dictionaries', dictionaries)
    pointer = json.loads((dictionaries / 'current.json').read_text())
    vendor = dictionaries / pointer['generation']
    manifest = json.loads((vendor / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest
    assert 'MIT License' in (vendor / 'lemminflect.LICENSE').read_text()
    assert 'MIT License' in (vendor / 'cspell-rust.LICENSE').read_text()
    project = tmp_path / 'project'
    (project / '.understand-anything').mkdir(parents=True)
    graph = {'nodes': [{'id': 'auth', 'summary': 'Handles authentication.'}]}
    (project / '.understand-anything/knowledge-graph.json').write_text(json.dumps(graph))
    cmd = [sys.executable, '-I', '-S', str(payload / 'skills/understand-chat/scripts/query_graph.py'), str(project),
           'Where is this beautiful authentication handled?']
    env = dict(os.environ, UA_DICTIONARY_DIR=str(dictionaries))
    env.pop('UA_ENGINE_BINARY', None)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['matchedNodes'] == graph['nodes']
    cache = project / '.understand-anything/query-dictionaries'
    cache.mkdir()
    words = b'["GET"]'
    digest = hashlib.sha256(words).hexdigest()
    filename = f'python-{digest}.json'
    (cache / filename).write_bytes(words)
    (cache / 'manifest.json').write_text(json.dumps({
        'version': 3,
        'lemmaSha256': hashlib.sha256(__import__('gzip').decompress((vendor / 'lemmas.json.gz').read_bytes()).strip()).hexdigest(),
        'graphSha256': hashlib.sha256(
            (project / '.understand-anything/knowledge-graph.json').read_bytes()
        ).hexdigest(),
        'dictionaries': {'python': {'file': filename, 'sha256': digest}},
    }))
    (vendor / 'cspell.json.gz').rename(vendor / 'disabled-cspell.gz')
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert json.loads(result.stdout)['matchedNodes'] == graph['nodes']
    (vendor / 'lemmas.json.gz').rename(vendor / 'disabled.gz')
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert result.stdout == ''
    assert 'No such file' in result.stderr or 'missing' in result.stderr
    assert 'Traceback' not in result.stderr
    (vendor / 'lemmas.json.gz').write_bytes(b'corrupt gzip data')
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert 'checksum mismatch' in result.stderr
    assert 'Traceback' not in result.stderr
