"""Capture graph analytics, including Spearman and topology scenarios."""
import check_reference  # Verify the frozen baseline before recapturing.
import json,pathlib,sys,random
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'core'))
from understand_core.analyze import analyze
from understand_core.models import AnalysisInput
random.seed(42)
cases=[]
paths=['src/api/routes.py','src/models/user.py','src/utils/helpers.py','docs/readme.md','Dockerfile','k8s/deployment.yaml','.github/workflows/test.yml','tests/test_api.py','schema.sql','package.json']
for n in [0,1,2,3,5,10]:
    for mode in ['none','chain','cycle','dense']:
        nodes=[dict(id=f'file:{p}',filePath=p,type='file' if i%3 else 'config',name=p,tags=[],summary='sample',complexity='simple') for i,p in enumerate(paths[:n])]
        edges=[]
        for a in range(n):
            for b in range(n):
                if (mode=='chain' and b==a+1) or (mode=='cycle' and b==(a+1)%n) or (mode=='dense' and random.random()<.3):
                    edges.append(dict(source=nodes[a]['id'],target=nodes[b]['id'],type='imports',weight=1,direction='forward'))
        data=dict(fileNodes=nodes,importEdges=edges,allEdges=edges)
        result=analyze(AnalysisInput.model_validate(data))
        # Topological order is nondeterministic for unrelated groups only.
        cases.append(dict(input=data,expected=result))
(ROOT/'tests/fixtures/analytics.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'analytics cases')
