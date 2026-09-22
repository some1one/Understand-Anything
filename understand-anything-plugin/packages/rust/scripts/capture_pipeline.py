"""Capture deterministic seed/finalize and partition pipeline contracts."""
import check_reference  # Verify the frozen baseline before recapturing.
import json,pathlib,sys,copy,tempfile,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
CORE=ROOT.parent/'core'
sys.path.insert(0,str(CORE))
from understand_core import file_graph
from understand_core.seed_file_batch_graph import build_seed
from understand_core.prepare_file_analysis_batch import build_batch_payloads
from understand_core.finalize_file_batch_output import graph_fragment,validate_draft,split_into_parts
from understand_core.validate_structure_output import check_structure_output
from understand_core.assemble_part_graph import build_part_graph
cases=[]
def add(fn,args,expected):cases.append(dict(function=fn,input=args,expected=expected))
paths=['src/main.py','src/test_main.py','index.ts','mod.rs','src/MyTest.java','README.md','package.json','Dockerfile','compose.yml','.github/workflows/a.yml','main.tf','db.sql','schema.graphql','service.proto','view.css','unknown.txt']
for category in [None,'code','script','config','docs','infra','data','markup']:
    for path in paths:
        add('file_graph',dict(path=path,category=category),dict(node=file_graph.file_level_node(category,path),tags=file_graph.deterministic_tags(category,path),test=file_graph.is_test_file(path)))
files=[dict(path=p,language='python',sizeLines=100,fileCategory=c) for p,c in [('src/main.py','code'),('src/lib.py','code'),('docs/readme.md','docs'),('Dockerfile','infra'),('package.json','config'),('schema.graphql','data'),('db.sql','data')]]
context=dict(projectRoot='/project',batchIndex=0,batchFiles=files,batchImportData={'src/main.py':['src/lib.py','src/main.py','other.py'],'src/lib.py':[]},neighborMap={})
results=dict(scriptCompleted=True,filesAnalyzed=len(files),filesSkipped=[],results=[dict(path=f['path'],language='python',fileCategory=f['fileCategory'],totalLines=100,nonEmptyLines=50,metrics=dict(functionCount=3,classCount=2,importCount=2),functions=[dict(name='short',startLine=1,endLine=2),dict(name='long',startLine=3,endLine=20),dict(name='exported',startLine=21,endLine=23)],classes=[dict(name='One',startLine=1,endLine=4,methods=['a']),dict(name='Two',startLine=1,endLine=4,methods=['a','b'])],exports=[dict(name='exported',line=21,isDefault=False)]) for f in files])
seed=build_seed(context,results)
add('seed',dict(context=context,results=results),seed)
for draft in [graph_fragment(seed),{**graph_fragment(seed),'nodes':seed['nodes'][1:]},{**graph_fragment(seed),'edges':[]},copy.deepcopy(graph_fragment(seed))]:
    if draft is not None:add('draft',dict(context=context,seed=seed,draft=draft),validate_draft(context,seed,draft))
for size in [0,60,61,120,121]:
    nodes=[dict(id=f'file:f{i}.py',filePath=f'f{i}.py') for i in range(size)]
    edges=[dict(source=f'file:f{i}.py',target='file:other.py') for i in range(size)]
    paths=[f'f{i}.py' for i in range(size)]
    add('split',dict(nodes=nodes,edges=edges,files=paths),split_into_parts(nodes,edges,paths))
for data in [results,{**results,'filesAnalyzed':0},{**results,'results':results['results'][:-1]},{**results,'results':results['results']+[results['results'][0]]}]:
    add('structure_check',dict(context=context,results=data),check_structure_output(context,data))
batch=dict(batchIndex=0,files=files,batchImportData=context['batchImportData'],neighborMap={})
add('batch_payloads',dict(root='/project',batch=batch),build_batch_payloads('/project',batch))
(ROOT/'tests/fixtures/pipeline.json').write_text(json.dumps(cases,indent=2)+'\n')
commands=[]
with tempfile.TemporaryDirectory() as tmp:
    root=pathlib.Path(tmp);inter=root/'.understand-anything/intermediate';inter.mkdir(parents=True)
    context={**context,'projectRoot':str(root)}
    def write(path,value):path.write_text(json.dumps(value,indent=2))
    write(root/'context.json',context);write(root/'results.json',results);write(inter/'batches.json',{'batches':[batch]})
    write(inter/'scan-result.json',dict(name='demo',description='desc',files=files+[dict(path='other.py')],languages=['python'],frameworks=[]))
    sequence=[('prepare_file_analysis_batch',[str(root),'0']),('seed_file_batch_graph',[str(root/'context.json'),str(root/'results.json'),str(root/'seed.json')]),('finalize_file_batch_output',[str(root),str(root/'context.json'),str(root/'seed.json'),str(root/'seed.json')]),('validate_structure_output',[str(root/'context.json'),str(root/'results.json')])]
    for command,args in sequence:
        before={str(p.relative_to(root)):p.read_text().replace(tmp,'<ROOT>') for p in root.rglob('*') if p.is_file()}
        result=subprocess.run([sys.executable,'-m',f'understand_core.{command}',*args],cwd=CORE,capture_output=True,text=True)
        after={str(p.relative_to(root)):p.read_text().replace(tmp,'<ROOT>') for p in root.rglob('*') if p.is_file()}
        assert result.returncode==0,result.stderr
        commands.append(dict(command=command,args=[a.replace(tmp,'<ROOT>') for a in args],before=before,after=after,status=result.returncode,stdout=result.stdout.replace(tmp,'<ROOT>'),stderr=result.stderr.replace(tmp,'<ROOT>')))
(ROOT/'tests/fixtures/pipeline_commands.json').write_text(json.dumps(commands,indent=2)+'\n')
print(len(cases),'API cases,',len(commands),'command cases')
