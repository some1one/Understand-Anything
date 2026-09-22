"""Capture existing normalization/linking tests with their original batch inputs."""
import check_reference,json,pathlib,sys,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core import merge_batch_graphs as m
cases=[]
for name in ['merge_and_normalize','normalize_node_id','normalize_complexity','classify_id_fix','is_test_path','production_candidates','normalize_direction','link_tests']:
    original=getattr(m,name)
    def capture(*args,_fn=original,_name=name,**kwargs):
        before=copy.deepcopy(list(args));result=_fn(*args,**kwargs)
        cases.append(dict(function=_name,args=before,expected=result,after=copy.deepcopy(list(args))))
        return result
    setattr(m,name,capture)
import pytest
assert pytest.main([str(CORE/'tests/test_merge_batch_graphs.py'),str(CORE/'tests/test_merge_recover_imports.py'),'-q'])==0
(ROOT/'tests/fixtures/merging.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'merging fixtures')
