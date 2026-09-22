"""Fail if the frozen Python working-tree baseline has drifted (development only)."""
import hashlib,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
CORE=ROOT.parent/'core'
baseline=json.loads((ROOT/'reference/baseline.json').read_text())
checks=[(CORE/m['python'],m['sha256']) for m in baseline['modules']]
checks.extend((CORE/'understand_core/schemas'/name,digest) for name,digest in baseline['schemas'].items())
checks.extend((CORE/name,digest) for name,digest in baseline['dependency_files'].items())
failed=[]
for path,expected in checks:
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        failed.append(str(path.relative_to(CORE)))
if failed:
    print('Reference drift:\n'+'\n'.join(failed),file=sys.stderr)
    raise SystemExit(1)
print(f'Frozen reference unchanged: {len(checks)} files')
