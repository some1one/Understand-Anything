"""Capture every invocation in the existing import resolution test scenarios."""
import check_reference,json,pathlib,sys,copy
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core';sys.path.insert(0,str(CORE))
from understand_core import extract_import_map as m
original=m.extract_import_map
cases=[]
def capture(input):
    root=pathlib.Path(input['projectRoot'])
    files={str(p.relative_to(root)):p.read_text() for p in root.rglob('*') if p.is_file()}
    out=original(input)
    cases.append(dict(input={**input,'projectRoot':'<ROOT>'},files=files,expected=out))
    return out
m.extract_import_map=capture
import pytest
assert pytest.main([str(CORE/'tests/test_import_map.py'),'-q'])==0
(ROOT/'tests/fixtures/imports.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'import-resolution fixtures')
