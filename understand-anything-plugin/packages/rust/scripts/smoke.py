#!/usr/bin/env python3
"""Exercise the release engine on an isolated snapshot; never change source artifacts.

Python is only this development test driver. Every engine subprocess runs with an
empty PATH, disabled embedding credentials and unreachable network proxies.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[2]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2))
    return path


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=PACKAGE/'target/release/understand-anything-rs')
    parser.add_argument('--parser-cache', type=Path, default=PACKAGE/'target/smoke-parsers')
    args = parser.parse_args()
    binary, cache = args.binary.resolve(), args.parser_cache.resolve()
    workspace = Path(tempfile.mkdtemp(prefix='ua-rust-smoke-'))
    project = workspace/'project'
    project.mkdir()
    artifacts = workspace/'checks'
    artifacts.mkdir()
    print(f'Smoke artifacts: {workspace}', flush=True)
    paths = sorted(set(subprocess.check_output(['git', '-C', str(REPO), 'ls-files', '-co', '--exclude-standard', '-z']).decode().split('\0')) - {''})
    snapshot = {}
    for rel in paths:
        # Analyze source, not installed plugin copies or previous analysis artifacts.
        if rel.split('/')[0].startswith('.') and not rel.startswith('.github/') and rel not in {'.gitignore', '.understandignore'}:
            continue
        source = REPO/rel
        if not source.is_file() or source.is_symlink():
            continue
        dest = project/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        snapshot[rel] = hashlib.sha256(source.read_bytes()).hexdigest()
    env = {**os.environ, 'PATH': '', 'UNDERSTAND_EMBEDDINGS_API_KEY': '',
           'HTTP_PROXY': 'http://127.0.0.1:1', 'HTTPS_PROXY': 'http://127.0.0.1:1',
           'ALL_PROXY': 'http://127.0.0.1:1'}
    results = []

    def run(command, *arguments):
        start = time.monotonic()
        result = subprocess.run([str(binary), '--parser-cache-dir', str(cache), command,
                                 *map(str, arguments)], cwd=project, env=env,
                                capture_output=True, text=True, timeout=180)
        number = len(results) + 1
        (artifacts/f'{number:03}-{command}.stdout').write_text(result.stdout)
        (artifacts/f'{number:03}-{command}.stderr').write_text(result.stderr)
        results.append(dict(command=command, arguments=list(map(str, arguments)),
                            status=result.returncode, seconds=round(time.monotonic()-start, 3)))
        write(workspace/'commands.json', results)
        if result.returncode:
            raise RuntimeError(f'{command} returned {result.returncode}:\n{result.stderr}\nSee {workspace}')
        return result.stdout

    run('--version')
    run('parsers', 'list')
    # A warm-cache fetch proves the test cannot silently pass with empty extraction.
    run('parsers', 'fetch')
    run('json_schema', '--output-dir', artifacts/'schemas')
    assert len(list((artifacts/'schemas').glob('*.json'))) == 16
    run('generate_ignore', project)
    scan_path = artifacts/'scan.json'
    run('scan_project', project, scan_path)
    scan = read(scan_path)
    assert scan['totalFiles'] > 100, scan['totalFiles']
    import_input = write(artifacts/'import-input.json', dict(projectRoot=str(project), files=scan['files']))
    imports_path = artifacts/'imports.json'
    run('extract_import_map', import_input, imports_path)
    imports = read(imports_path)
    assert imports['stats']['totalEdges'] > 0, 'Import resolution returned an empty graph'
    narrative = write(artifacts/'narrative.json', dict(name='Rust smoke snapshot', description='Isolated deterministic smoke test of current repository source.', languages=[], frameworks=[]))
    run('assemble_project_scan_result', project, narrative, '--scan', scan_path, '--import-map', imports_path)
    run('extract_domain_context', project)
    run('detect_layout', project)
    run('partition_files', project, '--depth=1')
    run('compute_batches', project)
    inter = project/'.ua/intermediate'
    batches = read(inter/'batches.json')['batches']
    assert batches
    covered = [f['path'] for b in batches for f in b['files']]
    assert sorted(covered) == sorted(f['path'] for f in scan['files']), 'Batches lost or duplicated files'
    def process_batch(batch):
        idx = batch['batchIndex']
        run('prepare_file_analysis_batch', project, idx)
        tmp = project/'.ua/tmp'
        batch_input = tmp/f'ua-file-analyzer-input-{idx}.json'
        context = tmp/f'ua-file-context-{idx}.json'
        structure = artifacts/f'structure-{idx}.json'
        run('extract_structure', batch_input, structure)
        run('validate_structure_output', batch_input, structure)
        extracted = read(structure)
        assert not extracted['filesSkipped'], extracted['filesSkipped']
        functions = sum(len(f.get('functions', [])) for f in extracted['results'])
        seed = artifacts/f'seed-{idx}.json'
        run('seed_file_batch_graph', context, structure, seed)
        # Stand in for the opt-in LLM stage with the deterministic, validated seed.
        run('finalize_file_batch_output', project, context, seed, seed)
        return functions

    functions = 0
    for number, batch in enumerate(batches, 1):
        functions += process_batch(batch)
        print(f'Batch {number}/{len(batches)}: {len(batch["files"])} files passed', flush=True)
    assert functions > 100, f'Unexpectedly few extracted functions: {functions}'
    run('merge_batch_graphs', project)
    assembled = inter/'assembled-graph.json'
    run('validate_assembled_graph', assembled, artifacts/'assembled-review.json', '--scan-result', inter/'scan-result.json')
    review = read(artifacts/'assembled-review.json')
    assert not review['issues'], review['issues'][:10]
    run('generate_input', project, artifacts/'architecture-input.json')
    run('analyze', artifacts/'architecture-input.json', artifacts/'architecture-results.json')
    run('assemble_part_graph', project, 'smoke', 'smoke-baseline')
    run('merge_parts', project)
    run('merge_subdomain_graphs', project)
    graph_path = project/'.ua/knowledge-graph.json'
    graph = read(graph_path)
    assert graph['nodes'] and graph['edges']
    file_types = {'file', 'config', 'document', 'service', 'pipeline', 'table', 'schema', 'resource', 'endpoint'}
    file_nodes = [n for n in graph['nodes'] if n['type'] in file_types]
    layer_input = write(artifacts/'layer-input.json', dict(fileNodes=file_nodes, importEdges=[], allEdges=[]))
    layers = [dict(id=f'layer:smoke-{i}', name=f'Smoke group {i}', description='Synthetic layer assignments for deterministic validation.', nodeIds=[n['id'] for n in file_nodes[i::3]]) for i in range(3)]
    layer_path = write(artifacts/'layers.json', layers)
    run('validate_layers', layer_input, layer_path)
    graph['layers'] = layers
    write(graph_path, graph)
    run('validate_graph', graph_path, artifacts/'graph-review.json')
    assert not read(artifacts/'graph-review.json')['issues']
    domain = dict(version='1.0.0', project=graph['project'], layers=[],
                  nodes=[dict(id=f'{kind}:smoke', type=kind, name=f'Smoke {kind}', summary='Exercises the deterministic smoke validation process.', tags=['smoke', 'validation', 'testing'], complexity='simple') for kind in ['domain', 'flow', 'step']],
                  edges=[dict(source='domain:smoke', target='flow:smoke', type='contains_flow', direction='forward', weight=0.5), dict(source='flow:smoke', target='step:smoke', type='flow_step', direction='forward', weight=0.5)])
    domain_path = write(artifacts/'domain.json', domain)
    run('validate_domain_graph', domain_path, artifacts/'domain-review.json')
    assert not read(artifacts/'domain-review.json')['issues']
    run('write_config', project, '--depth=1', '--parts=understand-anything-plugin,scripts')
    changed_list = artifacts/'changed.txt'
    changed_list.write_text('understand-anything-plugin/packages/rust/src/lib.rs\n')
    assert run('affected_parts', project, changed_list).strip() == 'understand-anything-plugin'
    assert 'understand-anything-plugin' in run('parts_to_process', project, '--full').splitlines()

    fingerprint_input = write(artifacts/'fingerprint-input.json', dict(projectRoot=str(project), sourceFilePaths=[f['path'] for f in scan['files']], gitCommitHash='smoke-baseline'))
    run('build_fingerprints', fingerprint_input)
    fingerprints = read(project/'.ua/fingerprints.json')
    assert len(fingerprints['files']) == scan['totalFiles']
    # Exercise the metadata-only path without changing or creating Git history.
    run('auto_update_preflight', project)
    write(inter/'auto-update-state.json', dict(changedSourceFiles=[], currentCommit='smoke-baseline'))
    run('auto_update_fingerprint_check', project)
    assert read(inter/'change-analysis.json')['action'] == 'SKIP'
    run('auto_update_prepare_batches', project)
    run('auto_update_apply_batches', project)
    run('auto_update_finalize', project)
    assert read(inter/'auto-update-summary.json')['status'] == 'UPDATED'
    # A real source edit in the temporary snapshot exercises structural reanalysis,
    # graph pruning/merging and fingerprint refresh, beyond the no-change branch.
    changed_source = 'understand-anything-plugin/packages/rust/src/scan.rs'
    source = project/changed_source
    source.write_text(source.read_text() + '\nfn smoke_added_helper(value: i32) -> i32 {\n    let current = value + 1;\n    current + 2\n}\n')
    write(inter/'auto-update-state.json', dict(changedSourceFiles=[changed_source], currentCommit='smoke-updated'))
    run('auto_update_fingerprint_check', project)
    analysis = read(inter/'change-analysis.json')
    assert analysis['action'] == 'PARTIAL_UPDATE', analysis
    assert analysis['filesToReanalyze'] == [changed_source]
    run('auto_update_prepare_batches', project)
    for batch in read(inter/'batches.json')['batches']:
        process_batch(batch)
    run('auto_update_apply_batches', project)
    run('auto_update_finalize', project)
    assert read(inter/'auto-update-summary.json')['structuralChanges'] == 1
    run('validate_graph', graph_path, artifacts/'updated-graph-review.json')
    assert not read(artifacts/'updated-graph-review.json')['issues']
    updated = read(project/'.ua/fingerprints.json')['files'][changed_source]
    assert updated['contentHash'] != fingerprints['files'][changed_source]['contentHash']
    expected_commands = {r['command'] for r in read(PACKAGE/'reference/baseline.json')['modules'] if r['command']}
    assert expected_commands <= {r['command'] for r in results}
    assert all(hashlib.sha256((REPO/rel).read_bytes()).hexdigest() == digest for rel, digest in snapshot.items()), 'Source snapshot changed during smoke test'
    report = dict(status='passed', sourceFilesCopied=len(snapshot), filesScanned=scan['totalFiles'], batches=len(batches), functionsExtracted=functions, importEdges=imports['stats']['totalEdges'], graphNodes=len(graph['nodes']), graphEdges=len(graph['edges']), subprocesses=len(results), commandContracts=len(expected_commands), structuralUpdate='passed', emptyRuntimePath=True, offline=True, sourceUnchanged=True, workspace=str(workspace))
    write(workspace/'report.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
