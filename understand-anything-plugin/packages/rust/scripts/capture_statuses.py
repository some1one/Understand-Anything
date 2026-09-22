"""Capture missing-argument statuses without writing to the source reference."""
import check_reference,json,pathlib,sys,tempfile,os,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1];CORE=ROOT.parent/'core'
rows=json.loads((ROOT/'reference/baseline.json').read_text())['modules'];cases=[]
for row in rows:
    command=row['command']
    # json_schema without --output-dir writes Python source schemas: never invoke it.
    if not command or command=='json_schema':continue
    for args in ([[]] if command!='generate_input' else [[],['--help'],['--unknown'],['missing','out.json'],['root','out.json','--include'],['root','out.json','--exclude']]):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp,'root').mkdir()
            env={**os.environ,'PYTHONPATH':str(CORE),'UNDERSTAND_EMBEDDINGS_API_KEY':''}
            result=subprocess.run([sys.executable,'-m','understand_core.'+command,*args],cwd=tmp,env=env,capture_output=True,text=True)
            cases.append(dict(command=command,args=args,status=result.returncode,aliases=row['aliases']))
(ROOT/'tests/fixtures/statuses.json').write_text(json.dumps(cases,indent=2)+'\n')
print(len(cases),'command status cases')
