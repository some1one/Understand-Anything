"""Regenerate development comparison fixtures with the frozen Python reference."""
import check_reference  # Verify the frozen baseline before recapturing.
import dataclasses
import hashlib
import json
import pathlib
import random
import sys
import tempfile
import subprocess

ROOT=pathlib.Path(__file__).resolve().parents[1]
CORE=ROOT.parent/'core'
sys.path.insert(0,str(CORE))
baseline=json.loads((ROOT/'reference/baseline.json').read_text())
for row in baseline['modules']:
    actual=hashlib.sha256((CORE/row['python']).read_bytes()).hexdigest()
    if actual!=row['sha256']: raise SystemExit(f'Reference drift: {row["python"]}')
from understand_core import partition_files as part, detect_layout, languages, schema, fingerprints, search, embedding_search
from understand_core.structure import parsers, registry
from understand_core.merge_subdomain_graphs import merge_graphs
from understand_core.boundary_stubs import add_boundary_stubs
from rapidfuzz import fuzz
cases=[]
def add(fn, args, expected):
    cases.append(dict(function=fn,input=args,expected=expected))
paths=['src/api/main.ts','src/api/lib.ts','src/lib/x.ts','src/root.ts','README.md','apps/shop/package.json','packages/core/Cargo.toml','./src/élève.py',' src\\api\\foo.rs ']
for sources in [[],['src'],['src/','src/api'],['./src','apps']]:
    for depth in [None,1,2,4]:
        if not sources and depth is None: continue
        add('partition',dict(paths=paths,sources=sources,depth=depth),part.partition_files(paths,sources=sources,depth=depth))
for p in [[],paths,['src/foo.py'],['lib/a.rb'],['README.md'],['pnpm-workspace.yaml'],['packages/a/package.json','packages/b/Cargo.toml']]:
    add('layout',dict(paths=p),detect_layout.detect_layout(p))
for p in paths+['.env','.env.production','.envrc','src/.env.local','.github/workflows/build.yml','compose.yaml','docker-compose.dev.yaml','LICENSE','k8s/service.txt','deploy/foo.k8s.YML','Dockerfile.dev','makefile','.config','archive.tar.gz','Foo.TSX','file','CMakeLists.txt']:
    add('detection',dict(path=p),dict(language=languages.detect_language(p),category=languages.detect_category(p),registry=registry.detect_registry_language(p)))
for patterns in [['build/','!build/keep.ts'],['*.ts','!src/keep.ts'],['a/**','!a/b/**','a/b/no.ts'],['/root.txt','*.log','!important.log'],['foo/','!foo/','foo/private/']]:
    for p in ['build/keep.ts','build/drop.ts','src/keep.ts','a/b/yes.ts','a/b/no.ts','root.txt','sub/root.txt','important.log','foo/private/a','foo/public/a']:
        add('ignore',dict(patterns=patterns,path=p),languages.IgnoreFilter(patterns).is_ignored(p))
samples={
'markdown':['# Hello\ntext\n## World\n','```md\n# Hidden\n```\n# Shown\n','~~~\n# not a heading\n~~~\n### Unicode 文\n',''],
'yaml':['name: demo\nservices:\n  web: app\n','- name: web\n- id: worker\n- 3\n','broken: [\nnext: key\n','"quoted key": true\nother: x\n','a: &a [1, 2]\nb: *a\n'],
'json':['{"a":1,"b":2}','// comment\n{\n "url": "https://example.com",\n "b": [1,],\n}\n','{bad','[]','{"text":"/* literal */","value":true}'],
'env':['# comment\nFOO=bar\nexport BAD=no\nUNICODE=文\n EMPTY=\n'],
'toml':['[package]\nname="x"\n[[bin]]\nname="a"\n[dependencies.dev]\n'],
'dockerfile':['FROM python:3.14 AS build\nRUN echo hi\nEXPOSE 80 443/tcp\nFROM alpine\nCOPY --from=build /app /app\n'],
'sql':['CREATE TABLE IF NOT EXISTS users (id INT, name TEXT, PRIMARY KEY(id));\nCREATE OR REPLACE VIEW active AS SELECT * FROM users;\nCREATE UNIQUE INDEX idx ON users(id);\n','CREATE TABLE broken\n'],
'graphql':['type User {\n id: ID!\n name: String\n}\ntype Query {\n user: User\n}\nscalar Date\n','input Form {\n a: String\n}\nenum Role {\n ADMIN\n USER\n}\n'],
'protobuf':['message User {\n string name = 1;\n repeated int32 ids = 2;\n}\nenum Role {\n ADMIN = 0;\n}\nservice Users {\n rpc Find (User) returns (User);\n}\n'],
'terraform':['resource "aws_s3_bucket" "assets" {\n tags = { Name = "test" }\n}\ndata "aws_region" "current" {}\nmodule "web" {}\nvariable "name" {}\noutput "id" {}\n'],
'makefile':['.PHONY: build\nVAR := value\nbuild: dep\n\techo hello\n\nnext:\n  echo world\n'],
'shell':['function one() {\n echo hi\n}\ntwo()\n{\n echo bye\n}\nnot_fn()\n# none\n']}
for lang,contents in samples.items():
    for content in contents+['']:
        a=dataclasses.asdict(parsers.get_parser_for_language(lang).analyze_file(content))
        a={k:v for k,v in a.items() if v is not None}
        add('noncode',dict(language=lang,content=content),a)
random.seed(42)
for a,b in [('abc','xyzabcx'),('abc','bc'),('a b','b a'),('',''),('你好','你们好')]+[(''.join(random.choices('abcd ',k=random.randrange(1,12))),''.join(random.choices('abcd ',k=random.randrange(1,20)))) for _ in range(160)]:
    add('fuzz',dict(a=a,b=b),[fuzz.partial_ratio(a,b)/100,fuzz.token_set_ratio(a,b)/100])
nodes=[dict(id='1',type='file',name='Authentication',tags=['login'],summary='Session management',languageNotes=''),dict(id='2',type='function',name='logout',tags=['authentication'],summary='End a session'),dict(id='3',type='class',name='User',tags=[],summary='A person')]
for q in ['auth','LOGIN','session','end user','zzzz','', ' authentication  ']:
    for types in [None,['function']]:
        add('search',dict(nodes=nodes,query=q,types=types),[dataclasses.asdict(r) for r in search.SearchEngine(nodes).search(q,types=types)])
for a,b in [([0,0],[1,1]),([1,0],[1,0]),([1,0],[-1,0]),([1,2,3],[3,2,1])]:
    add('cosine',dict(a=a,b=b),embedding_search.cosine_similarity(a,b))
project=dict(name='demo',languages=['python'],frameworks=[],description='Test',analyzedAt='',gitCommitHash='abc')
node=dict(id='file:a',type='file',name='a',summary='a',tags=[],complexity='simple',filePath='a',extension={'keep':True})
graph=dict(version='1.0.0',project=project,nodes=[node],edges=[],layers=[])
for g in [None,{},graph,{**graph,'nodes':[]},{**graph,'layers':None},{**graph,'nodes':[{**node,'type':'FN','filePath':None}]},{**graph,'nodes':[{**node,'complexity':'HIGH'}]},{**graph,'edges':[dict(source='file:a',target='file:missing',type='calls',direction='forward',weight=.5)]}]:
    add('validate',dict(graph=g),schema.validate_graph(g))
# Defaults exercise issue order, extension preservation, and malformed collections.
for g in [{**graph,'nodes':[dict(id='a',name='a')]},{**graph,'nodes':{}},{**graph,'edges':'bad'}]:
    add('validate',dict(graph=g),schema.validate_graph(g))
stub={**node,'stub':True,'summary':'stub'}
for graphs in [[graph,{**graph,'nodes':[stub]}],[{**graph,'nodes':[stub]},graph],[graph,graph]]:
    merged,report=merge_graphs(graphs)
    add('merge',dict(graphs=graphs),dict(graph=merged,report=report))
boundary={**graph,'edges':[dict(source='file:a',target='function:b:run',type='imports')]}
add('stubs',dict(graph=boundary,known=['a','b']),add_boundary_stubs(boundary,{'a','b'}))
a=parsers.EnvParser().analyze_file('FOO=one\n')
fp=fingerprints.extract_file_fingerprint('x.env','FOO=one\n',a)
for new in [fp,{**fp,'contentHash':'new'},{**fp,'contentHash':'new','hasStructuralAnalysis':False},{**fp,'contentHash':'new','exports':['foo']}]:
    add('compare_fingerprints',dict(old=fp,new=new),fingerprints.compare_fingerprints(fp,new))
for count in [0,1,10,11,30,31]:
    for total in [0,10,100]:
        changes=[dict(filePath=f'src/{i}.py',changeLevel='STRUCTURAL',status='modified') for i in range(count)]
        paths={f'src/{i}.py' for i in range(total)}
        add('classify_update',dict(changes=changes,paths=sorted(paths)),fingerprints.classify_update(changes,paths))
(ROOT/'tests/fixtures/reference.json').write_text(json.dumps(cases,indent=2,ensure_ascii=False)+'\n')
# Capture command streams/status and every output artifact, with temp roots canonicalized.
commands=[]
with tempfile.TemporaryDirectory() as tmp:
    root=pathlib.Path(tmp)
    ua=root/'.understand-anything'
    (ua/'intermediate').mkdir(parents=True)
    scan={'files':[{'path':p} for p in paths]}
    for command,args in [('detect_layout',[str(root)]),('partition_files',[str(root),'--depth=1']),('write_config',[str(root),'--depth=1','--parts=src']),('parts_to_process',[str(root),'--full'])]:
        (ua/'intermediate/scan-result.json').write_text(json.dumps(scan))
        before={str(p.relative_to(root)):p.read_text() for p in root.rglob('*') if p.is_file()}
        result=subprocess.run([sys.executable,'-m',f'understand_core.{command}',*args],cwd=CORE,capture_output=True,text=True)
        after={str(p.relative_to(root)):p.read_text() for p in root.rglob('*') if p.is_file()}
        commands.append(dict(command=command,args=[a.replace(tmp,'<ROOT>') for a in args],before=before,after=after,status=result.returncode,stdout=result.stdout.replace(tmp,'<ROOT>'),stderr=result.stderr.replace(tmp,'<ROOT>')))
(ROOT/'tests/fixtures/commands.json').write_text(json.dumps(commands,indent=2)+'\n')
print(f'{len(cases)} API cases and {len(commands)} command cases captured')
