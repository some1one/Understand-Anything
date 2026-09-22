"""Capture existing repair tests and malformed strict-schema boundary cases."""
import check_reference,json,pathlib,sys,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core import schema as m,json_schema as js
cases=[]
for name in ['validate_graph','sanitize_graph','normalize_graph','auto_fix_graph']:
    original=getattr(m,name)
    def capture(*args,_fn=original,_name=name,**kwargs):
        result=_fn(*args,**kwargs)
        cases.append(dict(function=_name,args=copy.deepcopy(list(args)),expected=copy.deepcopy(result)));return result
    setattr(m,name,capture)
import pytest
assert pytest.main([str(CORE/'tests/test_schema.py'),'-q'])==0
# Supplement coercions, invalid values and extension metadata.
p=dict(name='demo',languages=[],frameworks=[],description='',analyzedAt='',gitCommitHash='')
n=dict(id='a',name='a',type='file',summary='summary',tags=[],complexity='simple')
base=dict(project=p,nodes=[n],edges=[],layers=[])
for node in [None,{},dict(n,name=4),dict(n,tags=[3]),dict(n,domainMeta=[]),dict(n,complexity='not-a-level'),dict(n,extension=None)]:m.validate_graph(dict(base,nodes=[n,node]))
for weight in [True,False,'0.25',{},[],2,-3,1.5]:m.validate_graph(dict(base,edges=[dict(source='a',target='a',type='imports',direction='forward',weight=weight)]))
(ROOT/'tests/fixtures/validation.json').write_text(json.dumps(cases,indent=2)+'\n')
strict=[]
for file,model in js._SCHEMA_MODELS.items():
    # Covers required, type, enum, constraints, nested errors and extra-property handling.
    samples=[None,{},[],{'unexpected':True}]
    props=model.model_json_schema().get('properties',{})
    for v in [None,False,0,'',[],{},['bad']]:samples.append({key:v for key in props})
    for value in samples:
        try:js._validate(value,file);expected=None
        except js.SchemaValidationError as e:expected=str(e)
        strict.append(dict(schema=file.name,input=value,expected=expected))
(ROOT/'tests/fixtures/strict_schemas.json').write_text(json.dumps(strict,indent=2)+'\n')
print(len(cases),'repair fixtures;',len(strict),'strict-schema fixtures')
