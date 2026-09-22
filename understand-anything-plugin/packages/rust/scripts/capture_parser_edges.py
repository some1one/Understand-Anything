"""Capture long fuzzy matches and non-code format edge cases."""
import check_reference,dataclasses,json,pathlib,random,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT.parent/'core'))
from understand_core.structure.parsers import get_parser_for_language
from rapidfuzz import fuzz
cases=[]
samples={
'yaml':['on: push\ntrue: yes\nfalse: no\nnull: value\n3: foo\n','"on": x\n"true": x\n','- name: yes\n- id: null\n- kind: foo\n','a: one\nb: two\na: three\n','a: 1\n---\nb: 2','defaults: &base\n  name: web\n<<: *base\nlast: okay\n','? [a, b]\n: x\n'],
'json':['{"文": true, "a": 1}','{"\\u6587": true, "a": 1}','{"a": 1, "a": 2}','{"a": NaN}', '{"a": Infinity}'],
'openapi':['openapi: 3.0.0\npaths:\n  /foo:\n    get: {}\n','{"openapi":"3.0.0","paths":{}}'],
'docker-compose':['services:\n  web:\n    image: nginx\n    ports: ["80:80"]\nnetworks: {}\n'],
'github-actions':['name: build\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n'],
'kubernetes':['apiVersion: v1\nkind: Deployment\nmetadata:\n  name: app\n'],
'jenkinsfile':["pipeline {\n stages {\n stage('Build') {\n steps { sh 'make' }\n }\n }\n}\n"],
'markdown':['# 文\r\n### A\r\n','## notcode\n````\n# no\n~~~\n# no2\n````\n# yes'],
'sql':['CREATE TABLE "文" (id INT);\nCREATE TABLE `user` (\n id INT,\n -- comment\n name VARCHAR(30),\n CONSTRAINT foo CHECK (id>0)\n);'],
}
for language,contents in samples.items():
    parser=get_parser_for_language(language)
    if parser is None:continue
    for content in contents:
        result=dataclasses.asdict(parser.analyze_file(content));result={k:v for k,v in result.items() if v is not None}
        cases.append(dict(function='noncode',input=dict(language=language,content=content),expected=result))
random.seed(42)
for n in [64,65,80,100]:
    for alphabet in ['abcd ','abcdef0123456789你好']:
        a=''.join(random.choices(alphabet,k=n));b=''.join(random.choices(alphabet,k=n*2))
        cases.append(dict(function='fuzz',input=dict(a=a,b=b),expected=[fuzz.partial_ratio(a,b)/100,fuzz.token_set_ratio(a,b)/100]))
(ROOT/'tests/fixtures/parser_edges.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'parser/scorer edge fixtures')
