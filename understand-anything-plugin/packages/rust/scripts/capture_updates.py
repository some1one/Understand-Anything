"""Capture update phase filesystem effects using existing Python regression tests."""
import check_reference,json,pathlib,sys,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core import auto_update_preflight as pre,auto_update_fingerprint_check as fp,auto_update_apply_batches as apply,auto_update_finalize as fin,auto_update_common as common
cases=[]
def files(root):
    return {str(p.relative_to(root)):p.read_text() for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts}
def clean(v,root):
    if isinstance(v,dict):return {k:('<TIME>' if k in ['lastAnalyzedAt','generatedAt','analyzedAt'] else clean(x,root)) for k,x in v.items()}
    if isinstance(v,list):return [clean(x,root) for x in v]
    if isinstance(v,str):return v.replace(str(root),'<ROOT>')
    return v
def clean_files(data,root):
    out={}
    for p,content in data.items():
        if p.endswith('.json'):
            try:out[p]=json.dumps(clean(json.loads(content),root));continue
            except ValueError:pass
        out[p]=content.replace(str(root),'<ROOT>')
    return out
for name,module in [('preflight',pre),('fingerprint_check',fp),('apply_batches',apply),('finalize',fin)]:
    original=module.run
    def capture(root,*args,_fn=original,_name=name,**kw):
        before=clean_files(files(root),root)
        git={}
        if _name=='preflight':
            current=common.git_head(root);meta=common.read_json(common.meta_path(root)) or {};previous=meta.get('gitCommitHash')
            git=dict(head=current,changed=common.git_changed_files(root,previous,current) if previous and current else None)
        try:result=_fn(root,*args,**kw);error=None
        except Exception as e:result=None;error=str(e);raise
        finally:cases.append(dict(function=_name,force=kw.get('force',args[0] if args else False),git=git,before=before,after=clean_files(files(root),root),expected=clean(result,root),error=error))
        return result
    module.run=capture
import pytest
assert pytest.main([str(CORE/'tests/test_auto_update_preflight.py'),str(CORE/'tests/test_auto_update_flow.py'),'-q'])==0
# Exercise stop/error branches and architecture finalization independently.
import tempfile
project=dict(name='demo',languages=[],frameworks=[],description='',analyzedAt='',gitCommitHash='old')
node=dict(id='file:src/a.py',type='file',name='a.py',summary='Useful',tags=[],complexity='simple',filePath='src/a.py')
graph=dict(version='1.0.0',project=project,nodes=[node],edges=[],layers=[])
def scenario(module,initial,head='new',changed=None,force=False):
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        for rel,value in initial.items():
            path=root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value if isinstance(value,str) else json.dumps(value))
        oldhead,olddiff=common.git_head,common.git_changed_files
        common.git_head=lambda _:head
        common.git_changed_files=lambda *_:changed
        try:
            try:module.run(root,force=force) if module is pre else module.run(root)
            except (FileNotFoundError,RuntimeError):pass
        finally:common.git_head,common.git_changed_files=oldhead,olddiff
base={'.understand-anything/knowledge-graph.json':graph,'.understand-anything/meta.json':{'gitCommitHash':'old'}}
for head,changed,force in [(None,None,False),('new',None,False),('new',[],False),('old',[],True),('new',['README.md'],False),('new',['src/a.py'],False)]:
    scenario(pre,{**base,'.understand-anything/.understandignore':'src/\n'},head,changed,force)
for module in [fp,apply,fin]:scenario(module,{})
scenario(apply,{'.understand-anything/intermediate/change-analysis.json':{}})
analysis=dict(action='ARCHITECTURE_UPDATE',rerunArchitecture=True,filesToReanalyze=[],deletedFiles=['src/old.py'],newFiles=[],fileChanges=[],reason='Architecture changed')
inter='.understand-anything/intermediate/'
scenario(apply,{**base,inter+'change-analysis.json':analysis,inter+'batch-2-part-1.json':dict(nodes=[dict(node,id='file:new/b.py',filePath='new/b.py')],edges=[]),inter+'batch-stale.json':dict(nodes=[dict(node,id='file:ignore.py')],edges=[])})
for layers in [[],[dict(id='layer:core',name='Core',description='Core code',nodeIds=['file:src/a.py','file:gone.py','file:src/a.py'])],None]:
    scenario(fin,{**base,inter+'merged-graph.json':dict(graph,nodes=[node,dict(node,id='file:other/b.py',filePath='other/b.py')],edges=[dict(source='gone',target='file:src/a.py')]),inter+'change-analysis.json':analysis,inter+'auto-update-state.json':{'currentCommit':'new'},inter+'layers.json':layers,inter+'scan-result.json':{},inter+'nested/keep.txt':'retained',inter+'scratch.txt':'temporary'})
scenario(fin,{**base,'.understand-anything/fingerprints.json':{},inter+'merged-graph.json':graph,inter+'change-analysis.json':analysis,inter+'auto-update-state.json':{'currentCommit':'new'}})
(ROOT/'tests/fixtures/updates.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'update phase fixtures')
