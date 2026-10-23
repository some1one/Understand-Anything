//! Runtime declaration possibilities obtained from AST constructs.
use crate::symbol_coverage::{entry, spelling};
use serde_json::{Value, json};
use tree_sitter_language_pack::Node;

fn text<'a>(node: &Node, content: &'a str) -> &'a str {
    content
        .get(node.start_byte()..node.end_byte())
        .unwrap_or("")
}
fn named_children(node: &Node) -> Vec<Node> {
    (0..node.child_count())
        .filter_map(|i| node.child(i as u32))
        .filter(Node::is_named)
        .collect()
}
pub(crate) fn literal(node: &Node, content: &str) -> Option<String> {
    let source = text(node, content);
    if !spelling(source) {
        return None;
    }
    if node.kind() == "simple_symbol" {
        return source.strip_prefix(':').map(str::to_owned);
    }
    if ["string", "delimited_symbol"].contains(&node.kind().as_str()) {
        let mut value = String::new();
        for child in named_children(node) {
            if child.named_child_count() > 0
                || ![
                    "string_fragment",
                    "string_content",
                    "string_start",
                    "string_end",
                ]
                .contains(&child.kind().as_str())
            {
                return None;
            }
            if ["string_fragment", "string_content"].contains(&child.kind().as_str()) {
                value.push_str(text(&child, content));
            }
        }
        return Some(value);
    }
    None
}
const ACCESSORS: &[&str] = &["attr", "attr_reader", "attr_writer", "attr_accessor"];
const INSTALLERS: &[&str] = &[
    "attr",
    "attr_reader",
    "attr_writer",
    "attr_accessor",
    "define_method",
    "define_singleton_method",
    "alias_method",
];

pub(crate) fn ruby(
    node: &Node,
    content: &str,
    scope: &Value,
    receiver_scope: &Value,
) -> Vec<Value> {
    let mut effects = vec![];
    if node.kind() == "alias" {
        let name = node.child_by_field_name("name");
        if !name.as_ref().is_some_and(|n| n.kind() == "global_variable") {
            effects.push(entry(
                node,
                scope,
                name.as_ref()
                    .and_then(|n| literal(n, content))
                    .or_else(|| crate::symbol_coverage::name(name, content)),
                Some("callable"),
                "Ruby alias declaration",
            ));
        }
        return effects;
    }
    if node.kind() != "call" {
        return effects;
    }
    let Some(method) = node.child_by_field_name("method") else {
        return effects;
    };
    let method = text(&method, content);
    let mut args = node
        .child_by_field_name("arguments")
        .map(|n| named_children(&n))
        .unwrap_or_default();
    let receiver = node.child_by_field_name("receiver");
    let owner = if receiver.as_ref().is_none_or(|n| text(n, content) == "self") {
        receiver_scope.clone()
    } else {
        json!({"kind":"unknown"})
    };
    if ACCESSORS.contains(&method) {
        let mut writer = ["attr_writer", "attr_accessor"].contains(&method);
        if method == "attr"
            && args.len() == 2
            && ["true", "false"].contains(&args[1].kind().as_str())
        {
            writer = args.pop().unwrap().kind() == "true";
        }
        for arg in args {
            let name = literal(&arg, content);
            if method != "attr_writer" {
                effects.push(entry(
                    &arg,
                    &owner,
                    name.clone(),
                    Some("callable"),
                    "Ruby accessor reader",
                ));
            }
            if writer {
                let mut effect = entry(
                    &arg,
                    &owner,
                    name.as_ref().map(|n| format!("{n}=")),
                    Some("callable"),
                    "Ruby accessor writer",
                );
                if name.is_none() {
                    effect["nameSuffix"] = json!("=");
                }
                effects.push(effect);
            }
        }
    } else if INSTALLERS.contains(&method) && !args.is_empty() {
        let name = literal(&args[0], content).map(|name| {
            if method == "define_singleton_method" {
                format!("self.{name}")
            } else {
                name
            }
        });
        effects.push(entry(
            node,
            &owner,
            name,
            Some("callable"),
            "Ruby method installer",
        ));
    } else if [
        "method",
        "public_method",
        "instance_method",
        "public_instance_method",
        "singleton_method",
    ]
    .contains(&method)
        && !args.is_empty()
    {
        let name = literal(&args[0], content);
        if name
            .as_ref()
            .is_none_or(|n| INSTALLERS.contains(&n.as_str()))
        {
            let owner = if method.contains("instance_method") {
                json!({"kind":"unknown"})
            } else {
                owner
            };
            effects.push(entry(
                node,
                &owner,
                None,
                Some("callable"),
                "Indirect method installer",
            ));
        }
    } else if [
        "eval",
        "exec",
        "class_eval",
        "module_eval",
        "instance_eval",
        "class_exec",
        "module_exec",
        "instance_exec",
        "send",
        "public_send",
        "__send__",
    ]
    .contains(&method)
    {
        effects.push(entry(
            node,
            &json!({"kind":"unknown"}),
            None,
            None,
            "Dynamic dispatch or code evaluation",
        ));
    }
    effects
}
