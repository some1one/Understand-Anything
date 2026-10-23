//! Explicit gaps in declaration coverage. Gaps are evidence against deletion,
//! not a list of runtime effects (which require separate analysis).
use serde_json::{Value, json};
use tree_sitter_language_pack::Node;
use unicode_normalization::UnicodeNormalization;

pub(crate) fn spelling(text: &str) -> bool {
    !text.contains(['\\', '`'])
        && !text.starts_with('@')
        && !text.starts_with("r#")
        && text.nfkc().eq(text.chars())
}
pub(crate) fn declaration_key(node: &Node) -> Option<Node> {
    node.child_by_field_name("name").or_else(|| {
        (node.kind() == "field_definition")
            .then(|| node.child_by_field_name("property"))
            .flatten()
    })
}
pub(crate) fn name(node: Option<Node>, content: &str) -> Option<String> {
    let node = node?;
    let text = content.get(node.start_byte()..node.end_byte())?;
    if !spelling(text) {
        return None;
    }
    match node.kind().as_str() {
        "identifier"
        | "property_identifier"
        | "private_property_identifier"
        | "field_identifier"
        | "type_identifier"
        | "constant"
        | "simple_identifier" => Some(text.to_owned()),
        "string" if text.len() >= 2 && (text.starts_with('\'') || text.starts_with('"')) => {
            // No interpolation or nested expression can establish a literal name.
            for i in 0..node.child_count() {
                let child = node.child(i as u32)?;
                if child.is_named()
                    && ![
                        "string_fragment",
                        "string_content",
                        "string_start",
                        "string_end",
                    ]
                    .contains(&child.kind().as_str())
                {
                    return None;
                }
            }
            Some(text[1..text.len() - 1].to_owned())
        }
        _ => None,
    }
}
pub(crate) fn entry(
    node: &Node,
    scope: &Value,
    name: Option<String>,
    kind: Option<&str>,
    reason: &str,
) -> Value {
    json!({"kind":kind,"scope":scope,"name":name,"lineRange":[node.start_position().row+1,node.end_position().row+1],"reason":reason})
}
pub(crate) fn gap(
    node: &Node,
    scope: &Value,
    receiver: &Value,
    content: &str,
    declaration: bool,
) -> Option<Value> {
    let ty = node.kind();
    if ["required_parameter", "optional_parameter"].contains(&ty.as_str())
        && (0..node.child_count()).any(|i| {
            node.child(i as u32).is_some_and(|child| {
                [
                    "accessibility_modifier",
                    "readonly",
                    "override_modifier",
                    "override",
                ]
                .contains(&child.kind().as_str())
            })
        })
    {
        return Some(entry(
            node,
            receiver,
            name(
                node.child_by_field_name("pattern")
                    .or_else(|| declaration_key(node)),
                content,
            ),
            Some("callable"),
            "Parameter-property callability is not covered by structural extraction",
        ));
    }
    if ["macro_invocation", "preproc_call", "preproc_function_def"].contains(&ty.as_str()) {
        return Some(entry(
            node,
            &json!({"kind":"unknown"}),
            None,
            None,
            "Declaration expansion is not verified",
        ));
    }
    let key = declaration_key(node)?;
    if declaration || ["variable_declarator", "alias"].contains(&ty.as_str()) {
        return None;
    }
    if [
        "public_field_definition",
        "field_definition",
        "method_signature",
        "abstract_method_signature",
    ]
    .contains(&ty.as_str())
    {
        return Some(entry(
            node,
            scope,
            name(Some(key), content),
            Some("callable"),
            "Class member is not verified by structural extraction",
        ));
    }
    if [
        "export_specifier",
        "import_specifier",
        "import_statement",
        "import_from_statement",
        "future_import_statement",
        "aliased_import",
        "generic_type",
        "nested_type_identifier",
        "type_parameter",
        "type_predicate",
        "mapped_type_clause",
        "required_parameter",
        "optional_parameter",
        "default_parameter",
        "typed_default_parameter",
        "parameter_declaration",
        "keyword_argument",
        "keyword_parameter",
        "block_parameter",
        "hash_splat_parameter",
        "splat_parameter",
        "scope_resolution",
        "variable_reference_pattern",
        "as_pattern",
        "enum_assignment",
        "enum_body",
    ]
    .contains(&ty.as_str())
    {
        return None;
    }
    Some(entry(
        node,
        scope,
        name(Some(key), content),
        None,
        &format!("Declaration surface is not covered: {ty}"),
    ))
}
