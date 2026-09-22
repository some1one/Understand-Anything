//! Validated wire records. Dynamic extension fields survive round trips; each
//! named record applies its own defaults and unknown-field policy.
use crate::{Error, Result};
use serde_json::{Value, json};
use std::sync::OnceLock;

pub fn catalog() -> &'static Value {
    static MODELS: OnceLock<Value> = OnceLock::new();
    MODELS.get_or_init(|| {
        serde_json::from_str(include_str!("../reference/models.json")).expect("model catalog")
    })
}
pub fn enum_values(name: &str) -> Vec<String> {
    static ENUMS: OnceLock<Value> = OnceLock::new();
    crate::strings(
        &ENUMS.get_or_init(|| {
            serde_json::from_str(include_str!("../reference/enums.json")).expect("enum catalog")
        })[name],
    )
}
fn invalid(path: &str, message: impl Into<String>) -> Error {
    Error::Validation {
        path: path.to_owned(),
        message: message.into(),
    }
}
fn normalize(value: &Value, schema: &Value, root: &Value, path: &str) -> Result<Value> {
    if let Some(reference) = schema["$ref"].as_str() {
        return normalize(
            value,
            root.pointer(reference.trim_start_matches('#'))
                .ok_or_else(|| invalid(path, "Unresolved model reference"))?,
            root,
            path,
        );
    }
    if let Some(choices) = schema["anyOf"].as_array() {
        let mut first_error = None;
        for choice in choices {
            match normalize(value, choice, root, path) {
                Ok(v) => return Ok(v),
                Err(e) => {
                    if first_error.is_none() {
                        first_error = Some(e);
                    }
                }
            }
        }
        return Err(first_error.unwrap_or_else(|| invalid(path, "Invalid union")));
    }
    if let Some(values) = schema["enum"].as_array() {
        if !values.contains(value) {
            let words: Vec<_> = values.iter().map(crate::schemas::python_repr).collect();
            let expected = if words.len() > 1 {
                format!(
                    "{} or {}",
                    words[..words.len() - 1].join(", "),
                    words.last().unwrap()
                )
            } else {
                words.join("")
            };
            return Err(invalid(path, format!("Input should be {expected}")));
        }
        return Ok(value.clone());
    }
    if let Some(expected) = schema.get("const") {
        return if expected == value {
            Ok(value.clone())
        } else {
            Err(invalid(
                path,
                format!("Input should be {}", crate::schemas::python_repr(expected)),
            ))
        };
    }
    let result = match schema["type"].as_str() {
        Some("null") => {
            if !value.is_null() {
                return Err(invalid(path, "Input should be None"));
            }
            value.clone()
        }
        Some("string") => {
            if !value.is_string() {
                return Err(invalid(path, "Input should be a valid string"));
            }
            value.clone()
        }
        Some("boolean") => {
            let b = value
                .as_bool()
                .or_else(|| match value.as_i64() {
                    Some(0) => Some(false),
                    Some(1) => Some(true),
                    _ => None,
                })
                .or_else(|| {
                    value
                        .as_str()
                        .and_then(|s| match s.to_lowercase().as_str() {
                            "0" | "off" | "f" | "false" | "n" | "no" => Some(false),
                            "1" | "on" | "t" | "true" | "y" | "yes" => Some(true),
                            _ => None,
                        })
                });
            json!(b.ok_or_else(|| invalid(path, "Input should be a valid boolean"))?)
        }
        Some("number" | "integer") => {
            let number = value
                .as_f64()
                .or_else(|| value.as_bool().map(|b| if b { 1. } else { 0. }))
                .or_else(|| {
                    value
                        .as_str()
                        .and_then(|s| s.trim().replace('_', "").parse::<f64>().ok())
                });
            let n = number.ok_or_else(|| {
                invalid(
                    path,
                    if schema["type"] == "integer" {
                        "Input should be a valid integer"
                    } else {
                        "Input should be a valid number"
                    },
                )
            })?;
            if schema["type"] == "integer" {
                if n.fract() != 0. {
                    return Err(invalid(
                        path,
                        "Input should be a valid integer, got a number with a fractional part",
                    ));
                }
                if value.is_i64() || value.is_u64() {
                    value.clone()
                } else {
                    json!(n as i64)
                }
            } else {
                json!(n)
            }
        }
        Some("array") => {
            let items = value
                .as_array()
                .ok_or_else(|| invalid(path, "Input should be a valid list"))?;
            let empty = json!({});
            let mut out = Vec::with_capacity(items.len());
            for (i, v) in items.iter().enumerate() {
                let item_schema = schema
                    .get("prefixItems")
                    .and_then(|s| s.get(i))
                    .or_else(|| schema.get("items"))
                    .unwrap_or(&empty);
                out.push(normalize(v, item_schema, root, &format!("{path}/{i}"))?);
            }
            json!(out)
        }
        Some("object") => {
            let object = value.as_object().ok_or_else(|| {
                invalid(
                    path,
                    match schema["title"].as_str() {
                        Some(title) => {
                            format!("Input should be a valid dictionary or instance of {title}")
                        }
                        None => "Input should be a valid dictionary".into(),
                    },
                )
            })?;
            if let Some(props) = schema["properties"].as_object() {
                let required = crate::strings(&schema["required"]);
                let mut out = serde_json::Map::new();
                for (key, spec) in props {
                    if let Some(v) = object.get(key) {
                        out.insert(
                            key.clone(),
                            normalize(v, spec, root, &format!("{path}/{key}"))?,
                        );
                    } else if required.contains(key) {
                        return Err(invalid(&format!("{path}/{key}"), "Field required"));
                    } else if let Some(default) = spec.get("default") {
                        out.insert(key.clone(), default.clone());
                    }
                }
                for (key, v) in object {
                    if props.contains_key(key) {
                        continue;
                    }
                    match schema["x-extra-policy"].as_str().unwrap_or("ignore") {
                        "forbid" => {
                            return Err(invalid(
                                &format!("{path}/{key}"),
                                "Extra inputs are not permitted",
                            ));
                        }
                        "allow" => {
                            out.insert(key.clone(), v.clone());
                        }
                        _ => {}
                    }
                }
                Value::Object(out)
            } else if schema["additionalProperties"].is_object() {
                let mut out = serde_json::Map::new();
                for (key, v) in object {
                    out.insert(
                        key.clone(),
                        normalize(
                            v,
                            &schema["additionalProperties"],
                            root,
                            &format!("{path}/{key}"),
                        )?,
                    );
                }
                Value::Object(out)
            } else {
                value.clone()
            }
        }
        _ => value.clone(),
    };
    // Field constraints are checked here, in declaration order, before the next field.
    let mut constraints = schema.clone();
    if let Some(obj) = constraints.as_object_mut() {
        for key in [
            "properties",
            "required",
            "additionalProperties",
            "items",
            "prefixItems",
        ] {
            obj.remove(key);
        }
    }
    if let Ok(validator) = jsonschema::draft202012::new(&constraints)
        && let Some(error) = validator.iter_errors(&result).next()
    {
        use jsonschema::error::ValidationErrorKind as K;
        let message = match error.kind() {
            K::MinLength { limit } => format!(
                "String should have at least {limit} character{}",
                if *limit == 1 { "" } else { "s" }
            ),
            K::Minimum { limit } => format!("Input should be greater than or equal to {limit}"),
            K::Maximum { limit } => format!("Input should be less than or equal to {limit}"),
            K::Pattern { pattern } => format!("String should match pattern '{pattern}'"),
            _ => error.to_string(),
        };
        return Err(invalid(path, message));
    }
    Ok(result)
}
pub fn validate_model(name: &str, value: &Value) -> Result<Value> {
    let schema = catalog()
        .get(name)
        .ok_or_else(|| Error::Invalid(format!("Unknown model: {name}")))?;
    let result = normalize(value, schema, schema, "")?;
    if name == "_GraphEdgeModel"
        && !enum_values("FullEdgeType").contains(&result["type"].as_str().unwrap_or("").to_owned())
    {
        return Err(invalid("/type", "Value error, invalid edge type"));
    }
    Ok(result)
}
fn omit_null_fields(value: &Value, schema: &Value, root: &Value) -> Value {
    if let Some(reference) = schema["$ref"].as_str() {
        return omit_null_fields(
            value,
            root.pointer(reference.trim_start_matches('#'))
                .unwrap_or(&Value::Null),
            root,
        );
    }
    if let Some(choices) = schema["anyOf"].as_array()
        && let Some(spec) = choices.iter().find(|s| s["type"] != "null")
    {
        return omit_null_fields(value, spec, root);
    }
    if let (Some(object), Some(props)) = (value.as_object(), schema["properties"].as_object()) {
        return Value::Object(
            object
                .iter()
                .filter(|(_, v)| !v.is_null())
                .map(|(k, v)| {
                    (
                        k.clone(),
                        props
                            .get(k)
                            .map_or_else(|| v.clone(), |spec| omit_null_fields(v, spec, root)),
                    )
                })
                .collect(),
        );
    }
    if let Some(items) = value.as_array()
        && let Some(spec) = schema.get("items")
    {
        return json!(
            items
                .iter()
                .map(|v| omit_null_fields(v, spec, root))
                .collect::<Vec<_>>()
        );
    }
    value.clone()
}
pub fn exclude_model_none(name: &str, value: &Value) -> Value {
    omit_null_fields(value, &catalog()[name], &catalog()[name])
}
macro_rules! records {
    ($($name:ident),* $(,)?) => {$ (
        #[derive(Debug,Clone,PartialEq,serde::Serialize)]
        #[serde(transparent)]
        pub struct $name(Value);
        impl $name {
            pub fn from_value(value: Value)->Result<Self> { validate_model(stringify!($name),&value).map(Self) }
            pub fn as_value(&self)->&Value {&self.0}
            pub fn into_value(self)->Value {self.0}
            pub fn without_nulls(&self)->Value {exclude_model_none(stringify!($name),&self.0)}
        }
        impl TryFrom<Value> for $name {type Error=Error;fn try_from(value:Value)->Result<Self>{Self::from_value(value)}}
        impl std::ops::Deref for $name {type Target=Value;fn deref(&self)->&Value{&self.0}}
        impl<'de> serde::Deserialize<'de> for $name {fn deserialize<D:serde::Deserializer<'de>>(d:D)->std::result::Result<Self,D::Error>{Self::from_value(Value::deserialize(d)?).map_err(serde::de::Error::custom)}}
    )*};
}
records!(
    FileNode,
    Edge,
    AnalysisInput,
    AnalysisResult,
    ScanFile,
    ScanStats,
    ScanResult,
    ImportMapFile,
    ImportMapInput,
    ImportMapStats,
    ImportMapResult,
    StructureBatchFile,
    StructureInput,
    StructureResult,
    StructureOutput,
    Layer,
    LayersOutput,
    ProjectScanOutput,
    GraphNode,
    DomainNode,
    GraphEdge,
    GraphProject,
    KnowledgeGraph,
    DomainGraph,
    GraphFragment,
    NeighborEntry,
    FileAnalysisContext,
    AutoUpdateState,
    FileChangeResult,
    ChangeAnalysis,
    UpdateDecision,
    ProjectConfig,
    AutoUpdateSummary,
    KnowledgeMeta,
    DomainMeta,
    ThemeConfig,
    AnalysisMeta,
    TypesProjectConfig,
    SectionInfo,
    DefinitionInfo,
    ServiceInfo,
    EndpointInfo,
    StepInfo,
    ResourceInfo,
    ReferenceResolution,
    FunctionInfo,
    ClassInfo,
    ImportInfo,
    ExportInfo,
    StructuralAnalysis,
    ImportResolution,
    CallGraphEntry
);
pub type ProjectMeta = GraphProject;
