//! Receiver identities shared by extraction and strict symbol evidence.
use tree_sitter_language_pack::Node;
pub(crate) fn go(node: &Node, source: &str) -> Option<String> {
    let receiver = node.child_by_field_name("receiver")?;
    let declaration = (0..receiver.child_count())
        .filter_map(|i| receiver.child(i as u32))
        .find(|node| node.kind() == "parameter_declaration")?;
    let mut ty = declaration.child_by_field_name("type")?;
    if ty.kind() == "pointer_type" {
        ty = ty.named_child(0)?;
    }
    if ty.kind() == "generic_type" {
        ty = ty.child_by_field_name("type")?;
    }
    if ty.kind() != "type_identifier" {
        return None;
    }
    let name = source.get(ty.start_byte()..ty.end_byte())?;
    crate::symbol_coverage::spelling(name).then(|| name.to_owned())
}

pub(crate) fn rust(node: &Node, source: &str) -> Option<String> {
    // A trait method needs both trait and receiver identity. Do not silently
    // equate it with an inherent method on the same type.
    if node.child_by_field_name("trait").is_some() {
        return None;
    }
    let ty = node.child_by_field_name("type")?;
    let name = source.get(ty.start_byte()..ty.end_byte())?;
    (!name.is_empty() && crate::symbol_coverage::spelling(name)).then(|| name.to_owned())
}

/// A function definition's declarator supplies the name in C/C++, unlike
/// languages with a direct `name` field. Keep qualified receivers intact.
pub(crate) fn cpp<'a>(node: &Node, source: &'a str) -> Option<(&'a str, Option<&'a str>)> {
    cpp_declarator(&node.child_by_field_name("declarator")?, source)
}

pub(crate) fn cpp_declarator<'a>(declaration: &Node, source: &'a str) -> Option<(&'a str, Option<&'a str>)> {
    if declaration.kind() != "function_declarator" { return None; }
    let declarator = declaration.child_by_field_name("declarator")?;
    let mut name = declarator.clone();
    while name.kind() == "qualified_identifier" {
        name = name.child_by_field_name("name")?;
    }
    if !["identifier", "field_identifier"].contains(&name.kind().as_str()) { return None; }
    let owner = if declarator.kind() == "qualified_identifier" {
        Some(source.get(declarator.start_byte()..name.start_byte())?.trim_end().strip_suffix("::")?.trim_end())
    } else { None };
    let name = source.get(name.start_byte()..name.end_byte())?;
    crate::symbol_coverage::spelling(name).then_some((name, owner))
}
