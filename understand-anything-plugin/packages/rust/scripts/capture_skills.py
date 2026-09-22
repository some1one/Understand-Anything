"""Capture prompt-builder reference output; development only."""
import check_reference  # Verify the frozen baseline before recapturing.
import json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'core'))
from understand_core.types import KnowledgeGraph
from skill_builders import context_builder as chat, explain_builder as explain, diff_analyzer as diff, onboard_builder as onboard
node=lambda id,path,typ='file',**kw:dict(id=id,name=id,filePath=path,type=typ,summary='Summary '+id,tags=['alpha'],complexity='simple',**kw)
g=dict(version='1.0.0',project=dict(name='Demo',description='Demo project',languages=['Python'],frameworks=['FastAPI'],analyzedAt='2026-01-01',gitCommitHash='abc'),nodes=[node('a','a.py'),node('b','b.py'),node('run','a.py','function',lineRange=[1,3]),node('concept',None,'concept')],edges=[dict(source='a',target='run',type='contains',direction='forward',weight=1),dict(source='b',target='a',type='imports',direction='forward',weight=.8)],layers=[dict(id='layer:core',name='Core',description='Shared core',nodeIds=['a','run']),dict(id='layer:app',name='App',description='Application',nodeIds=['b'])])
graph=KnowledgeGraph.model_validate(g)
cases=[]
for path in ['a.py','a.py:run','missing.py']:
    c=explain.build_explain_context(graph,path)
    cases.append(dict(function='explain',input=dict(graph=g,path=path),context=c.model_dump(exclude_none=True),prompt=explain.format_explain_prompt(c)))
for changed in [[],['a.py'],['b.py','new.py']]:
    c=diff.build_diff_context(graph,changed)
    cases.append(dict(function='diff',input=dict(graph=g,changed=changed),context=c.model_dump(exclude_none=True),prompt=diff.format_diff_analysis(c)))
cases.append(dict(function='onboard',input=dict(graph=g),prompt=onboard.build_onboarding_guide(graph)))
# Use the captured context for deterministic rendering: Python set order is incidental.
for query in ['alpha','zzzz']:
    c=chat.build_chat_context(graph,query)
    cases.append(dict(function='chat',input=dict(graph=g,query=query),context=c.model_dump(exclude_none=True),prompt=chat.format_context_for_prompt(c)))
(ROOT/'tests/fixtures/skills.json').write_text(json.dumps(cases,indent=2)+'\n')
