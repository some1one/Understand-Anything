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
