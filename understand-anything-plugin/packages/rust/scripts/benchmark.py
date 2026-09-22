"""Informational Unix benchmark; Python is a development reference only."""
import argparse,json,os,pathlib,subprocess,sys,tempfile,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
CORE=ROOT.parent/'core'
p=argparse.ArgumentParser()
p.add_argument('--parser-cache',required=True)
p.add_argument('--output',default=str(ROOT/'reference/benchmark.json'))
p.add_argument('--iterations',type=int,default=100)
a=p.parse_args()
binary=ROOT/'target/release/understand-anything-rs'
probe=ROOT/'target/release/examples/parse_benchmark'
def measure(args,env=None):
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        start=time.perf_counter()
        child=subprocess.Popen([str(x) for x in args],stdout=stdout,stderr=stderr,env=env)
        _,status,usage=os.wait4(child.pid,0)
        elapsed=time.perf_counter()-start
        child.returncode=os.waitstatus_to_exitcode(status)
        stdout.seek(0);stderr.seek(0)
        output=stdout.read().decode();err=stderr.read().decode()
        if child.returncode: raise RuntimeError(err)
        result=dict(wallSeconds=elapsed,peakRssKiB=usage.ru_maxrss/(1024 if sys.platform=='darwin' else 1))
        try: result['result']=json.loads(output)
        except ValueError: pass
        return result
with tempfile.TemporaryDirectory() as tmp:
    source=pathlib.Path(tmp)/'sample.py'
    source.write_text('def greet(name: str) -> str:\n    return "hello " + name\n\n'*100)
    env={**os.environ,'PYTHONPATH':str(CORE)}
    result={'platform':sys.platform,'machine':os.uname().machine,'python':sys.version.split()[0],
            'rustStartup':measure([binary,'--version']),
            'pythonStartup':measure([sys.executable,'-c','import understand_core'],env)}
    result['rustParsing']=measure([probe,a.parser_cache,'python',source,a.iterations])
    code='''import json,time,pathlib,sys
from understand_core.treesitter import parse
source=pathlib.Path(sys.argv[1]).read_text()
start=time.perf_counter(); tree=parse('python',source); first=time.perf_counter()-start
assert tree is not None
start=time.perf_counter()
for _ in range(int(sys.argv[2])): assert parse('python',source) is not None
print(json.dumps(dict(firstParseSeconds=first,warmParseSeconds=time.perf_counter()-start,iterations=int(sys.argv[2]))))
'''
    result['pythonParsing']=measure([sys.executable,'-c',code,source,a.iterations],env)
    result['notes']=['Single run, informational; no performance acceptance threshold.','First parse uses predownloaded grammars; cold network download is tested separately.','Parses a repeated 300-line synthetic Python source; excludes structural extraction.','Warm loop includes parser lookup/construction according to each public API.']
pathlib.Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
