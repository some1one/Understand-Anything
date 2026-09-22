"""Capture graph review and deterministic batching boundaries from the frozen tree."""
import check_reference
import json,pathlib,sys,copy,tempfile,subprocess,os
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core.validate_graph import review_graph,add_scan_coverage
from understand_core.validate_domain_graph import review_domain_graph
from understand_core.compute_batches import build_non_code_batches,merge_small_batches,count_based_assignment,compute_batches
cases=[]
def add(fn,input,expected):cases.append(dict(function=fn,input=input,expected=expected))
node=dict(id='file:a.py',type='file',name='a.py',filePath='a.py',summary='Details',tags=[],complexity='simple')
base=dict(nodes=[node],edges=[],layers=[])
graphs=[{},base,dict(nodes=[None,{},node,node,{'id':'bad','type':'unknown','summary':3,'tags':None}],edges=[None,{},dict(source='bad',target='absent',weight=True,type='bad',direction='bad')],layers=[None,{},dict(id='l',nodeIds=['absent'])]),dict(nodes=[node],edges=[dict(source='file:a.py',target='file:a.py',type='imports',direction='forward',weight=0.5)],layers=[dict(id='one',nodeIds=['file:a.py']),dict(id='two',nodeIds=['file:a.py'])])]
for t in ['function','class','document','service','pipeline','table','schema','domain','flow','step']:
    graphs.append(dict(nodes=[{**node,'type':t,'summary':'a.py'}],edges=[],layers=[]))
for graph in graphs:
    for layers in [True,False]:
        for scan in [None,['a.py','b.py'],[f'x{i}.py' for i in range(60)]]:
            review=review_graph(graph,require_layers=layers)
            if scan is not None:add_scan_coverage(review,graph,scan)
            add('review',dict(graph=graph,layers=layers,scan=scan),review)
for paths in [[],['a.txt'],['Dockerfile','.dockerignore','docker-compose.yml','other.yml','.github/workflows/a.yml','.gitlab-ci.yml','.circleci/a.yml','migration/1.sql','migration/2.sql','docs/readme.md'],[f'docs/{i}.md' for i in range(47)],[f'd{i}/a.md' for i in range(60)]]:
    files=[dict(path=p,fileCategory='docs') for p in paths]
    groups=build_non_code_batches(files)
    add('noncode_batches',dict(files=files),groups)
    add('merge_small',dict(batches=groups),merge_small_batches(groups))
    add('count_assignment',dict(files=files),count_based_assignment(files))
(ROOT/'tests/fixtures/review_batches.json').write_text(json.dumps(cases,indent=2)+'\n')
commands=[]
with tempfile.TemporaryDirectory() as tmp:
    root=pathlib.Path(tmp);(root/'.understand-anything/intermediate').mkdir(parents=True)
    (root/'graph.json').write_text(json.dumps(graphs[2]));(root/'scan.json').write_text(json.dumps({'files':[{'path':'missing.py'}]}))
    files=[dict(path=f'src/{i}.unknown',language='unknown',fileCategory='code') for i in range(29)]
    for f in files:
        p=root/f['path'];p.parent.mkdir(exist_ok=True);p.write_text('source\n')
    (root/'.understand-anything/intermediate/scan-result.json').write_text(json.dumps(dict(files=files,importMap={'src/0.unknown':['src/20.unknown']})))
    for command,args,env in [('validate_graph',[str(root/'graph.json'),str(root/'review.json'),'--scan-result',str(root/'scan.json')],{}),('validate_assembled_graph',[str(root/'graph.json'),str(root/'review2.json'),'--scan-result='+str(root/'scan.json')],{}),('compute_batches',[str(root)],{'UA_COMPUTE_BATCHES_FORCE_LOUVAIN_THROW':'1'})]:
        before={str(p.relative_to(root)):p.read_text().replace(tmp,'<ROOT>') for p in root.rglob('*') if p.is_file()}
        result=subprocess.run([sys.executable,'-m',f'understand_core.{command}',*args],cwd=CORE,env={**os.environ,**env},capture_output=True,text=True)
        after={str(p.relative_to(root)):p.read_text().replace(tmp,'<ROOT>') for p in root.rglob('*') if p.is_file()}
        assert result.returncode==0,result.stderr
        commands.append(dict(command=command,args=[a.replace(tmp,'<ROOT>') for a in args],env=env,before=before,after=after,status=result.returncode,stdout=result.stdout.replace(tmp,'<ROOT>'),stderr=result.stderr.replace(tmp,'<ROOT>')))
(ROOT/'tests/fixtures/review_commands.json').write_text(json.dumps(commands,indent=2)+'\n')
print(len(cases),'cases;',len(commands),'commands')
