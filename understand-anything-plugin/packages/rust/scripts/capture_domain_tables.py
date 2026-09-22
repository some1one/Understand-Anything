"""Freeze lightweight domain scanner tables, without changing baseline source."""
import check_reference,json,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT.parent/'core'))
from understand_core import extract_domain_context as d
out={k:sorted(getattr(d,k)) if isinstance(getattr(d,k),set) else getattr(d,k) for k in ['SOURCE_EXTENSIONS','SKIP_DIRS','METADATA_FILES']}
out['patterns']=[dict(type=t,description=desc,regex=p.pattern,flags=p.flags) for t,desc,p in d.ENTRY_POINT_PATTERNS]
(ROOT/'reference/domain_tables.json').write_text(json.dumps(out,indent=2)+'\n')
