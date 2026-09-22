//! Frozen Draft 2020-12 contracts.
use crate::{Error, Result};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
};
pub const SCHEMAS: &[(&str, &str)] = &[
    (
        "auto-update-state.schema.json",
        include_str!("../schemas/auto-update-state.schema.json"),
    ),
    (
        "auto-update-summary.schema.json",
        include_str!("../schemas/auto-update-summary.schema.json"),
    ),
    (
        "change-analysis.schema.json",
        include_str!("../schemas/change-analysis.schema.json"),
    ),
    (
        "domain-graph.schema.json",
        include_str!("../schemas/domain-graph.schema.json"),
    ),
    (
        "file-analysis-context.schema.json",
        include_str!("../schemas/file-analysis-context.schema.json"),
    ),
    (
        "graph-fragment.schema.json",
        include_str!("../schemas/graph-fragment.schema.json"),
    ),
    (
        "import-map-input.schema.json",
        include_str!("../schemas/import-map-input.schema.json"),
    ),
    (
        "import-map-output.schema.json",
        include_str!("../schemas/import-map-output.schema.json"),
    ),
    (
        "input.schema.json",
        include_str!("../schemas/input.schema.json"),
    ),
    (
        "knowledge-graph.schema.json",
        include_str!("../schemas/knowledge-graph.schema.json"),
    ),
    (
        "layers.schema.json",
        include_str!("../schemas/layers.schema.json"),
    ),
    (
        "output.schema.json",
        include_str!("../schemas/output.schema.json"),
    ),
    (
        "project-scan-output.schema.json",
        include_str!("../schemas/project-scan-output.schema.json"),
    ),
    (
        "scan-result.schema.json",
        include_str!("../schemas/scan-result.schema.json"),
    ),
    (
        "structure-input.schema.json",
        include_str!("../schemas/structure-input.schema.json"),
    ),
    (
        "structure-output.schema.json",
        include_str!("../schemas/structure-output.schema.json"),
    ),
];
pub fn load_schema(name: &str) -> Result<Value> {
    let full = if name.ends_with(".schema.json") {
        name.to_owned()
    } else {
        format!("{name}.schema.json")
    };
    let (_, raw) = SCHEMAS
        .iter()
        .find(|(n, _)| *n == full)
        .ok_or_else(|| Error::Invalid(format!("Unknown schema: {name}")))?;
    Ok(serde_json::from_str(raw)?)
}
pub fn validate(name: &str, data: &Value) -> Result<()> {
    let schema = load_schema(name)?;
    let validator =
        jsonschema::draft202012::new(&schema).map_err(|e| Error::Invalid(e.to_string()))?;
    let mut errors: Vec<_> = validator.iter_errors(data).collect();
    // Sort path components numerically for array indices, as Python does.
    errors.sort_by_key(|e| {
        let path = e
            .instance_path()
            .to_string()
            .split('/')
            .map(|s| {
                s.parse::<usize>()
                    .map(|i| format!("{i:020}"))
                    .unwrap_or_else(|_| s.to_owned())
            })
            .collect::<Vec<_>>();
        let schema_path = e.schema_path().to_string();
        let (parent, key) = schema_path.rsplit_once('/').unwrap_or(("", ""));
        let index = schema
            .pointer(parent)
            .and_then(Value::as_object)
            .and_then(|o| o.keys().position(|k| k == key))
            .unwrap_or(0);
        (path, index)
    });
    let errors: Vec<_> = errors
        .iter()
        .map(|e| {
            let path = e.instance_path().to_string();
            format!(
                "{}: {}",
                if path.is_empty() {
                    "<root>"
                } else {
                    path.trim_start_matches('/')
                },
                python_error(e)
            )
        })
        .collect();
    if errors.is_empty() {
        Ok(())
    } else {
        Err(Error::Invalid(errors.join("; ")))
    }
}
pub fn export(output_dir: &Path) -> Result<Vec<PathBuf>> {
    fs::create_dir_all(output_dir)?;
    let mut paths = vec![];
    for (name, raw) in SCHEMAS {
        let path = output_dir.join(name);
        fs::write(&path, raw)?;
        paths.push(path);
    }
    Ok(paths)
}

/// Python-style representations used in stable validator diagnostics.
pub fn python_repr(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::String(s) => {
            let quote = if s.contains('\'') && !s.contains('"') {
                '"'
            } else {
                '\''
            };
            let mut out = String::from(quote);
            for c in s.chars() {
                match c {
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    c if c == quote => {
                        out.push('\\');
                        out.push(c);
                    }
                    _ => out.push(c),
                }
            }
            out.push(quote);
            out
        }
        Value::Array(a) => format!(
            "[{}]",
            a.iter().map(python_repr).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(o) => format!(
            "{{{}}}",
            o.iter()
                .map(|(k, v)| format!(
                    "{}: {}",
                    python_repr(&Value::String(k.clone())),
                    python_repr(v)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        _ => value.to_string(),
    }
}
fn python_error(error: &jsonschema::ValidationError<'_>) -> String {
    use jsonschema::error::{TypeKind, ValidationErrorKind as K};
    let v = python_repr(error.instance());
    match error.kind() {
        K::Required { property } => format!("{} is a required property", python_repr(property)),
        K::Type {
            kind: TypeKind::Single(t),
        } => format!("{v} is not of type '{t}'"),
        K::Enum { options } => format!("{v} is not one of {}", python_repr(options)),
        K::Constant { expected_value } => format!("{} was expected", python_repr(expected_value)),
        K::AnyOf { .. } | K::OneOfNotValid { .. } => {
            format!("{v} is not valid under any of the given schemas")
        }
        K::AdditionalProperties { unexpected } => {
            let mut names = unexpected.clone();
            names.sort();
            format!(
                "Additional properties are not allowed ({} {} unexpected)",
                names
                    .iter()
                    .map(|n| python_repr(&Value::String(n.clone())))
                    .collect::<Vec<_>>()
                    .join(", "),
                if names.len() == 1 { "was" } else { "were" }
            )
        }
        K::MinLength { limit } | K::MinItems { limit } => {
            if *limit == 1 {
                format!("{v} should be non-empty")
            } else {
                format!("{v} is too short")
            }
        }
        K::MaxLength { .. } | K::MaxItems { .. } => format!("{v} is too long"),
        K::Pattern { pattern } => format!(
            "{v} does not match {}",
            python_repr(&Value::String(pattern.clone()))
        ),
        K::Minimum { limit } => format!("{v} is less than the minimum of {limit}"),
        K::Maximum { limit } => format!("{v} is greater than the maximum of {limit}"),
        _ => error.to_string(),
    }
}
