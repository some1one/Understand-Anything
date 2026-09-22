"""Capture remaining command contracts, statuses and owned filesystem effects."""
import check_reference,json,pathlib,sys,tempfile,subprocess,os
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core'
cases=[]
node=dict(id='file:src/a.py',type='file',name='a.py',filePath='src/a.py',summary='Performs a useful operation',tags=['python'],complexity='simple')
graph=dict(version='1.0.0',project=dict(name='demo',languages=['python'],frameworks=[],description='Demo project',analyzedAt='2026-01-01T00:00:00Z',gitCommitHash='abc'),nodes=[node],edges=[],layers=[])
file=dict(path='src/a.py',language='python',sizeLines=2,fileCategory='code')
scan=dict(name='demo',description='Demo project',languages=['python'],frameworks=[],files=[file],totalFiles=1,filteredByIgnore=0,estimatedComplexity='small',importMap={'src/a.py':[]})
def capture(command,files,args,env=None,status=0):
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        for p,v in files.items():
            path=root/p;path.parent.mkdir(parents=True,exist_ok=True)
            data=json.dumps(v,indent=2) if not isinstance(v,str) else v
            path.write_text(data.replace('<ROOT>',tmp))
        def snapshot():return {str(p.relative_to(root)):p.read_text().replace(tmp,'<ROOT>') for p in root.rglob('*') if p.is_file()}
        before=snapshot();result=subprocess.run([sys.executable,'-m','understand_core.'+command,*[s.replace('<ROOT>',tmp) for s in args]],cwd=CORE,env={**os.environ,'UA_EMBEDDINGS_ENABLED':'false',**(env or {})},capture_output=True,text=True)
        assert result.returncode==status,(command,result.stderr)
        cases.append(dict(command=command,args=args,env=env or {},before=before,after=snapshot(),stdout=result.stdout.replace(tmp,'<ROOT>'),stderr=''.join(line for line in result.stderr.replace(tmp,'<ROOT>').splitlines(keepends=True) if not line.startswith('<frozen runpy>:128: RuntimeWarning:')),status=status))
capture('scan_project',{'project/src/a.py':'def a():\n    return 1\n','project/.understandignore':'excluded/\n','project/excluded/b.py':'skip','project/README.md':'# 文\n'},['<ROOT>/project','<ROOT>/scan.json'])
capture('generate_ignore',{'project/src/a.py':'pass','project/node_modules/a.js':'skip'},['<ROOT>/project'])
capture('generate_ignore',{'project/.understand-anything/.understandignore':'keep\n'},['<ROOT>/project'])
capture('generate_input',{'project/src/a.py':'pass\n','project/README.md':'# test','project/.gitignore':'skip/\n','project/skip/a.py':'pass'},['<ROOT>/project','<ROOT>/input.json','--include','*.py','*.md'])
capture('analyze',{'input.json':dict(fileNodes=[node],importEdges=[],allEdges=[])},['<ROOT>/input.json','<ROOT>/results.json'])
capture('affected_parts',{'.understand-anything/config.json':dict(splitDepth=1,includedParts=['src','tests']),'changed.txt':'src/a.py\nvendor/b.py\ntests/test_a.py\n'},['<ROOT>','<ROOT>/changed.txt'])
capture('assemble_project_scan_result',{'scan.json':dict(files=[file],totalFiles=1,filteredByIgnore=0,estimatedComplexity='small'),'imports.json':dict(importMap={'src/a.py':[]}),'narrative.json':dict(name='demo',description='Demo project',languages=['python'],frameworks=[])},['<ROOT>','<ROOT>/narrative.json','--scan','<ROOT>/scan.json','--import-map','<ROOT>/imports.json'])
capture('extract_structure',{'src/a.py':'def a():\n    return 1\n','input.json':dict(projectRoot='<ROOT>',batchFiles=[file,{**file,'path':'missing.py'}],batchImportData={})},['<ROOT>/input.json','<ROOT>/results.json'])
capture('extract_import_map',{'src/a.py':'from . import b\n','src/b.py':'pass\n','input.json':dict(projectRoot='<ROOT>',files=[file,{**file,'path':'src/b.py'}])},['<ROOT>/input.json','<ROOT>/imports.json'])
capture('build_fingerprints',{'src/a.py':'def a():\n    return 1\n','input.json':dict(projectRoot='<ROOT>',sourceFilePaths=['src/a.py','missing.py'],gitCommitHash='abc')},['<ROOT>/input.json'])
capture('extract_domain_context',{'src/service.py':'from .helpers import help\n@app.route("/hello")\ndef hello():\n    return help()\n','README.md':'# Demo 文\n','package.json':dict(name='demo',scripts={'start':'run'},dependencies={'one':'*'})},['<ROOT>'])
capture('merge_batch_graphs',{'.understand-anything/intermediate/batch-1.json':dict(nodes=[node],edges=[]),'.understand-anything/intermediate/scan-result.json':scan},['<ROOT>'])
capture('assemble_part_graph',{'.understand-anything/intermediate/assembled-graph.json':dict(nodes=[node],edges=[]),'.understand-anything/intermediate/batch-1.json':dict(nodes=[node],edges=[]),'.understand-anything/intermediate/scan-result.json':scan},['<ROOT>','src','abc'])
for cmd in ['merge_parts','merge_subdomain_graphs']:
    capture(cmd,{'.understand-anything/partitions/src.knowledge-graph.json':graph},['<ROOT>'])
arch=dict(fileNodes=[{**node,'id':f'file:src/{i}.py','filePath':f'src/{i}.py'} for i in range(3)],importEdges=[],allEdges=[])
layers=[dict(id=f'layer:{i}',name=f'Layer {i}',description='Layer role',nodeIds=[f'file:src/{i}.py']) for i in range(3)]
capture('validate_layers',{'input.json':arch,'layers.json':layers},['<ROOT>/input.json','<ROOT>/layers.json'])
domain={**graph,'nodes':[dict(id='domain:x',type='domain',name='x',summary='Business domain',tags=[],complexity='simple')],'edges':[]}
capture('validate_domain_graph',{'domain.json':domain},['<ROOT>/domain.json'])
capture('auto_update_preflight',{},['<ROOT>'])
capture('auto_update_fingerprint_check',{'.understand-anything/intermediate/auto-update-state.json':dict(changedSourceFiles=[],currentCommit='abc'),'.understand-anything/knowledge-graph.json':graph},['<ROOT>'])
capture('auto_update_prepare_batches',{'src/a.py':'def a():\n    return 1\n','.understand-anything/knowledge-graph.json':graph,'.understand-anything/intermediate/change-analysis.json':dict(filesToReanalyze=['src/a.py'])},['<ROOT>'],env={'UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW':'1'})
analysis=dict(filesToReanalyze=[],deletedFiles=[],action='PARTIAL_UPDATE',fileChanges=[],reason='Test',rerunArchitecture=False)
capture('auto_update_apply_batches',{'.understand-anything/knowledge-graph.json':graph,'.understand-anything/intermediate/change-analysis.json':analysis},['<ROOT>'])
capture('auto_update_finalize',{'.understand-anything/intermediate/merged-graph.json':graph,'.understand-anything/intermediate/change-analysis.json':analysis,'.understand-anything/intermediate/auto-update-state.json':dict(currentCommit='abc'),'.understand-anything/intermediate/scan-result.json':scan},['<ROOT>'])
(ROOT/'tests/fixtures/additional_commands.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'command fixtures')
