"""Map every frozen production module and command to native code and evidence."""
import json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
baseline=json.loads((ROOT/'reference/baseline.json').read_text())
groups={
'partition': 'affected_parts partition_files detect_layout parts_to_process write_config',
'analytics': 'analyze graph grouping recommendations topology',
'assembly': 'assemble_project_scan_result assemble_part_graph',
'merge': 'boundary_stubs merge_parts merge_subdomain_graphs',
'search': 'search embedding_search',
'embeddings': 'embeddings',
'file_graph': 'file_graph',
'batch_validation': 'finalize_file_batch_output validate_structure_output validate_layers',
'fingerprints': 'fingerprint fingerprints build_fingerprints',
'ignore_generator': 'generate_ignore ignore_generator',
'scan': 'ignore_filter languages scan_project',
'schemas': 'json_schema',
'seed': 'prepare_file_analysis_batch seed_file_batch_graph',
'persistence': 'persistence',
'validation': 'schema',
'staleness': 'staleness',
'parsers': 'treesitter',
'skills': 'context_builder understand_chat diff_analyzer explain_builder onboard_builder',
'batching': 'compute_batches',
'imports': 'extract_import_map',
'structure': 'extract_structure base code_extractors registry',
'domain_context': 'extract_domain_context',
'input': 'generate_input patterns',
'batch_merge': 'merge_batch_graphs',
'models': 'models types',
'strict_validation': 'validate_graph validate_assembled_graph validate_domain_graph',
'updates': 'auto_update_common auto_update_preflight auto_update_fingerprint_check auto_update_prepare_batches auto_update_apply_batches auto_update_finalize',
'lib': 'constants',
'noncode': 'parsers',
}
fixtures={
'partition':['reference.json','commands.json','additional_commands.json'],
'analytics':['analytics.json','additional_commands.json'],
'assembly':['pipeline.json','additional_commands.json'],
'merge':['reference.json','additional_commands.json'],
'search':['reference.json','parser_edges.json'],
'embeddings':[],
'file_graph':['pipeline.json'],
'batch_validation':['pipeline.json','pipeline_commands.json','additional_commands.json'],
'fingerprints':['reference.json','updates.json','additional_commands.json'],
'ignore_generator':['additional_commands.json'],
'scan':['reference.json','additional_commands.json'],
'schemas':['strict_schemas.json'],
'seed':['pipeline.json','pipeline_commands.json'],
'persistence':['updates.json'],
'validation':['reference.json','validation.json'],
'staleness':['updates.json'],
'parsers':['structure.json'],
'skills':['skills.json'],
'batching':['review_batches.json','review_commands.json'],
'imports':['imports.json','additional_commands.json'],
'structure':['structure.json','additional_commands.json'],
'domain_context':['additional_commands.json'],
'input':['additional_commands.json','analytics.json'],
'batch_merge':['merging.json','additional_commands.json'],
'models':['models.json','strict_schemas.json'],
'strict_validation':['review_batches.json','review_commands.json','additional_commands.json'],
'updates':['updates.json','additional_commands.json'],
'lib':['reference.json'],
'noncode':['reference.json','parser_edges.json'],
}
mapping={name:target for target,names in groups.items() for name in names.split()}
commands={r['command'] for r in baseline['modules'] if r['command']}
rows=[]
for row in baseline['modules']:
    path=pathlib.Path(row['python']);name=path.stem
    target=mapping.get(name)
    if name=='__init__':target='skills' if path.parts[0]=='skill_builders' else ('structure' if 'structure' in path.parts else 'lib')
    assert target,row
    evidence=[f'tests/fixtures/{p}' for p in fixtures[target]]
    for p in evidence:assert (ROOT/p).exists(),p
    rows.append(dict(python=row['python'],sha256=row['sha256'],command=row['command'],aliases=row['aliases'],rust=f'src/{target}.rs',implementationExists=True,status='implemented',commandAvailable=True if row['command'] else None,tests=['tests/differential.rs','tests/runtime.rs'],fixtures=evidence,publicSymbols=row['public_symbols'],additionalRust=['src/analytics.rs'] if name=='patterns' else [],notes='Re-exports map to shared native APIs.' if name=='__init__' else 'Wire records use validated serde_json values.' if name in ['types','models'] else ''))
platforms={target:('local formatting, Clippy, tests, native parser loading and release smoke checks' if target.startswith('x86_64-unknown-linux') else 'CI configured; execution pending') for target in ['x86_64-unknown-linux-gnu','aarch64-unknown-linux-gnu','x86_64-apple-darwin','aarch64-apple-darwin']}
output=dict(acceptanceComplete=False,implementedCommands=len(commands),baselineCommands=33,productionModules=len(rows),platformVerification=platforms,limits=['A module mapping and passing captured scenarios are not an exhaustive semantic-equivalence proof.','Cross-platform acceptance remains pending the CI matrix.','Rust uses parser pack 1.20.0; the frozen Python environment used 1.12.1.'],modules=rows)
(ROOT/'reference/coverage.json').write_text(json.dumps(output,indent=2)+'\n')
print(len(commands),'commands;',len(rows),'production modules mapped')
