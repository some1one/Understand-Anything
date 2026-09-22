"""Freeze model defaults, unknown-field policies and wire contracts for Rust."""
import check_reference, json, pathlib, sys, typing
from pydantic import BaseModel
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core import models, types, schema
catalog={};enums={};classes={}
for module in [models,types,schema]:
    for name,cls in vars(module).items():
        if isinstance(cls,type) and issubclass(cls,BaseModel) and cls is not BaseModel and cls.__module__==module.__name__:
            key=('TypesProjectConfig' if module is types and name=='ProjectConfig' else name)
            classes[key]=cls
            record=cls.model_json_schema()
            catalog[key]=record
        elif typing.get_origin(cls) is typing.Literal:
            enums[name]=list(typing.get_args(cls))
# Default factories are absent from JSON Schema. Capture them without inventing defaults.
by_title={cls.__name__:cls for cls in classes.values()}
def augment(record,cls):
    record['x-extra-policy']=cls.model_config.get('extra','ignore')
    for name,field in cls.model_fields.items():
        if field.default_factory:
            prop=record.get('properties',{}).get(field.alias or name)
            if prop is not None:prop['default']=field.get_default(call_default_factory=True)
for name,record in catalog.items():
    augment(record,classes[name])
    for title,child in record.get('$defs',{}).items():
        if title in by_title:augment(child,by_title[title])
(ROOT/'reference/models.json').write_text(json.dumps(catalog,indent=2)+'\n')
(ROOT/'reference/enums.json').write_text(json.dumps(enums,indent=2)+'\n')
print(len(catalog),'models captured')
def sample(spec,root):
    if '$ref' in spec:return sample(root['$defs'][spec['$ref'].split('/')[-1]],root)
    if 'default' in spec:return spec['default']
    if 'enum' in spec:return spec['enum'][0]
    if 'const' in spec:return spec['const']
    if 'anyOf' in spec:return sample(spec['anyOf'][0],root)
    kind=spec.get('type')
    if kind=='object':return {key:sample(s,root) for key,s in spec.get('properties',{}).items() if key in spec.get('required',[])}
    if kind=='array':
        if 'prefixItems' in spec:return [sample(s,root) for s in spec['prefixItems']]
        return [sample(spec.get('items',{}),root) for _ in range(spec.get('minItems',0))]
    if kind=='string':return 'layer:test' if 'pattern' in spec else 'sample'
    if kind=='boolean':return True
    if kind in ['integer','number']:return spec.get('minimum',1)
    return None
fixtures=[]
for name,cls in classes.items():
    original=sample(catalog[name],catalog[name]);samples=[original]
    if isinstance(original,dict):
        samples.append(dict(original,extension={'future':None}))
        for field,spec in catalog[name].get('properties',{}).items():
            for value in [None,False,7,'7',[],{},'']:
                samples.append(dict(original,**{field:value}))
    for value in samples:
        try:
            obj=cls.model_validate(value)
            result=dict(valid=True,output=obj.model_dump(by_alias=True),withoutNulls=obj.model_dump(by_alias=True,exclude_none=True))
        except Exception as e:result=dict(valid=False)
        fixtures.append(dict(model=name,input=value,expected=result))
(ROOT/'tests/fixtures/models.json').write_text(json.dumps(fixtures,indent=2)+'\n')
print(len(fixtures),'model boundary fixtures')
