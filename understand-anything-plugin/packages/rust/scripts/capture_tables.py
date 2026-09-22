"""Freeze data tables; this does not execute during Rust builds or at runtime."""
import check_reference  # Verify the frozen baseline before recapturing.
import json
import pathlib
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent/'core'))
from understand_core import languages, constants, schema
from understand_core.structure import registry
out = {}
for module in [languages, constants, schema, registry]:
    values = {}
    for name, value in vars(module).items():
        if name.strip('_').isupper() and isinstance(value, (dict, list, tuple, set, frozenset)):
            try:
                json.dumps(value, default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else None)
                values[name] = value
            except TypeError:
                pass
    out[module.__name__.split('.')[-1]] = values
(ROOT/'reference/tables.json').write_text(json.dumps(out, indent=2, default=lambda v: sorted(v) if isinstance(v, (set, frozenset)) else None)+'\n')
# Embedded repair schemas are distinct from strict pipeline schemas.
for name in ['_GraphNodeModel', '_GraphEdgeModel', '_LayerModel', '_ProjectMetaModel']:
    (ROOT/'reference'/f'{name}.json').write_text(json.dumps(getattr(schema, name).model_json_schema(), indent=2)+'\n')
schemas = sorted((ROOT/'schemas').glob('*.json'))
source = '//! Frozen Draft 2020-12 contracts.\nuse crate::{Error, Result};\nuse serde_json::Value;\nuse std::{fs, path::{Path, PathBuf}};\npub const SCHEMAS: &[(&str, &str)] = &[\n'
for p in schemas:
    source += f'    ("{p.name}", include_str!("../schemas/{p.name}")),\n'
source += '''];
pub fn load_schema(name: &str) -> Result<Value> {
    let full = if name.ends_with(".schema.json") { name.to_owned() } else { format!("{name}.schema.json") };
    let (_, raw) = SCHEMAS.iter().find(|(n,_)| *n == full).ok_or_else(|| Error::Invalid(format!("Unknown schema: {name}")))?;
    Ok(serde_json::from_str(raw)?)
}
pub fn validate(name: &str, data: &Value) -> Result<()> {
    let schema = load_schema(name)?;
    let validator = jsonschema::draft202012::new(&schema).map_err(|e| Error::Invalid(e.to_string()))?;
    let mut errors = validator.iter_errors(data).map(|e| format!("{}: {}", e.instance_path(), e)).collect::<Vec<_>>();
    errors.sort();
    if errors.is_empty() { Ok(()) } else { Err(Error::Invalid(errors.join("; "))) }
}
pub fn export(output_dir: &Path) -> Result<Vec<PathBuf>> {
    fs::create_dir_all(output_dir)?;
    let mut paths = vec![];
    for (name, raw) in SCHEMAS { let path = output_dir.join(name); fs::write(&path, raw)?; paths.push(path); }
    Ok(paths)
}
'''
(ROOT/'src/schemas.rs').write_text(source)
