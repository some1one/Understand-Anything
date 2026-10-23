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
    bindings: &crate::symbol_bindings::Index,
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
        bindings.reference(receiver.as_ref().unwrap(), content)
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

fn member(node: &Node, content: &str) -> Option<(Node, Option<String>)> {
    match node.kind().as_str() {
        "member_expression" | "attribute" => Some((
            node.child_by_field_name("object")?,
            crate::symbol_coverage::name(
                node.child_by_field_name("property")
                    .or_else(|| node.child_by_field_name("attribute")),
                content,
            ),
        )),
        "subscript_expression" | "subscript" => Some((
            node.child_by_field_name("object")
                .or_else(|| node.child_by_field_name("value"))?,
            node.child_by_field_name("index")
                .or_else(|| node.child_by_field_name("subscript"))
                .as_ref()
                .and_then(|n| literal(n, content)),
        )),
        _ => None,
    }
}
fn target_scope(
    node: &Node,
    content: &str,
    receiver: &Value,
    javascript: bool,
    bindings: &crate::symbol_bindings::Index,
) -> Value {
    // `this` is a lexical receiver only when scope analysis has verified it.
    // Named variables (including Python's `self`) need binding-resolution evidence.
    if javascript && text(node, content) == "this" && receiver["kind"] == "class" {
        return receiver.clone();
    }
    if let Some((object, Some(name))) = member(node, content)
        && ["prototype", "__dict__"].contains(&name.as_str())
    {
        return target_scope(&object, content, receiver, javascript, bindings);
    }
    bindings.reference(node, content)
}
fn object_keys(
    object: Option<Node>,
    content: &str,
    owner: &Value,
    context: &Node,
    out: &mut Vec<Value>,
) {
    let Some(object) = object.filter(|n| ["object", "dictionary"].contains(&n.kind().as_str()))
    else {
        out.push(entry(
            context,
            owner,
            None,
            None,
            "Unresolved property descriptor collection",
        ));
        return;
    };
    for field in named_children(&object) {
        // Comments do not install properties; spreads and unknown key forms do.
        if field.kind() == "comment" {
            continue;
        }
        let key = field
            .child_by_field_name("key")
            .or_else(|| field.child_by_field_name("name"))
            .or_else(|| (field.kind() == "shorthand_property_identifier").then(|| field.clone()));
        let name = key.as_ref().and_then(|key| {
            if key.kind() == "computed_property_name" {
                key.named_child(0)
                    .as_ref()
                    .and_then(|n| literal(n, content))
            } else {
                crate::symbol_coverage::name(Some(key.clone()), content).or_else(|| {
                    (key.kind() == "shorthand_property_identifier" && spelling(text(key, content)))
                        .then(|| text(key, content).to_owned())
                })
            }
        });
        // Object-literal __proto__: changes inheritance rather than defining a
        // normal own property; inherited callables are not enumerated here.
        let name = if field.kind() == "pair"
            && name.as_deref() == Some("__proto__")
            && key
                .as_ref()
                .is_some_and(|key| key.kind() != "computed_property_name")
        {
            None
        } else {
            name
        };
        out.push(entry(
            &field,
            owner,
            name,
            None,
            "Runtime property definition",
        ));
    }
}
fn assignment_effects(
    target: &Node,
    content: &str,
    scope: &Value,
    receiver: &Value,
    javascript: bool,
    value: Option<Node>,
    bindings: &crate::symbol_bindings::Index,
    out: &mut Vec<Value>,
) {
    if let Some((object, name)) = member(target, content) {
        let owner = target_scope(&object, content, receiver, javascript, bindings);
        if javascript && name.as_deref() == Some("prototype") {
            object_keys(value, content, &owner, target, out);
        } else {
            out.push(entry(target, &owner, name, None, "Property assignment"));
        }
    } else if ["identifier", "shorthand_property_identifier_pattern"]
        .contains(&target.kind().as_str())
    {
        if scope["kind"] != "local" {
            out.push(entry(
                target,
                scope,
                spelling(text(target, content)).then(|| text(target, content).to_owned()),
                None,
                "Binding assignment",
            ));
        }
    } else if [
        "object_pattern",
        "array_pattern",
        "pair_pattern",
        "pattern_list",
        "tuple_pattern",
        "list_pattern",
        "parenthesized_expression",
    ]
    .contains(&target.kind().as_str())
    {
        let children = target
            .child_by_field_name("value")
            .map(|n| vec![n])
            .unwrap_or_else(|| named_children(target));
        for child in children {
            assignment_effects(
                &child, content, scope, receiver, javascript, None, bindings, out,
            );
        }
    }
}
/// JS/Python operations that can install or retain callable/class bindings.
/// Until installer and receiver bindings are proven, report unknown identity
/// instead of assuming a standard builtin or a same-spelled declaring class.
pub(crate) fn javascript_python(
    node: &Node,
    content: &str,
    scope: &Value,
    receiver: &Value,
    javascript: bool,
    bindings: &crate::symbol_bindings::Index,
    handled: &mut std::collections::BTreeSet<crate::symbol_bindings::Key>,
) -> Vec<Value> {
    let mut effects = vec![];
    let kind = node.kind();
    if [
        "assignment_expression",
        "augmented_assignment_expression",
        "assignment",
        "augmented_assignment",
        "variable_declarator",
    ]
    .contains(&kind.as_str())
    {
        if let Some(target) = node
            .child_by_field_name("left")
            .or_else(|| node.child_by_field_name("name"))
        {
            let value = if ["augmented_assignment_expression", "augmented_assignment"]
                .contains(&kind.as_str())
            {
                None
            } else {
                node.child_by_field_name("right")
                    .or_else(|| node.child_by_field_name("value"))
            };
            assignment_effects(
                &target,
                content,
                scope,
                receiver,
                javascript,
                value,
                bindings,
                &mut effects,
            );
        }
    }
    let js_installers = [
        "defineProperty",
        "defineProperties",
        "__defineGetter__",
        "__defineSetter__",
    ];
    let py_installers = ["setattr", "__setattr__", "new_class"];
    if (javascript && kind == "call_expression") || (!javascript && kind == "call") {
        if let Some(mut callee) = node.child_by_field_name("function") {
            while ["parenthesized_expression", "parenthesized_statements"]
                .contains(&callee.kind().as_str())
            {
                let children = named_children(&callee);
                if children.len() != 1 {
                    break;
                }
                callee = children[0].clone();
            }
            let access = member(&callee, content);
            let method = access
                .as_ref()
                .and_then(|(_, name)| name.clone())
                .or_else(|| crate::symbol_coverage::name(Some(callee.clone()), content));
            let args = node
                .child_by_field_name("arguments")
                .map(|n| named_children(&n))
                .unwrap_or_default();
            let installer = method.as_ref().is_some_and(|method| {
                if javascript {
                    js_installers.contains(&method.as_str())
                        || access.as_ref().is_some_and(|(object, _)| {
                            (text(object, content) == "Reflect" && method == "set")
                                || (text(object, content) == "Object" && method == "assign")
                        })
                } else {
                    py_installers.contains(&method.as_str())
                }
            });
            if installer {
                consume(&callee, handled);
                let standard = if javascript {
                    access.as_ref().is_some_and(|(namespace, _)| {
                        bindings.unbound(namespace, text(namespace, content))
                            && ((text(namespace, content) == "Object"
                                && ["defineProperty", "defineProperties", "assign"]
                                    .contains(&method.as_deref().unwrap_or("")))
                                || (text(namespace, content) == "Reflect"
                                    && ["defineProperty", "set"]
                                        .contains(&method.as_deref().unwrap_or(""))))
                    })
                } else {
                    access.is_none()
                        && method.as_deref() == Some("setattr")
                        && bindings.unbound(&callee, "setattr")
                };
                if !standard {
                    effects.push(entry(
                        node,
                        &json!({"kind":"unknown"}),
                        None,
                        None,
                        "Runtime installer identity is unresolved",
                    ));
                } else {
                    let owner = args
                        .first()
                        .map(|arg| target_scope(arg, content, receiver, javascript, bindings))
                        .unwrap_or(json!({"kind":"unknown"}));
                    match method.as_deref() {
                        Some("defineProperties") => {
                            object_keys(args.get(1).cloned(), content, &owner, node, &mut effects)
                        }
                        Some("assign") => {
                            for arg in args.iter().skip(1) {
                                object_keys(Some(arg.clone()), content, &owner, node, &mut effects);
                            }
                        }
                        _ => effects.push(entry(
                            node,
                            &owner,
                            args.get(1).and_then(|n| literal(n, content)),
                            None,
                            "Runtime property definition",
                        )),
                    }
                }
            } else if method.as_ref().is_some_and(|method| {
                (javascript && ["eval", "Function"].contains(&method.as_str()))
                    || (!javascript
                        && (["eval", "exec"].contains(&method.as_str())
                            || method == "type" && args.len() >= 3))
            }) {
                consume(&callee, handled);
                effects.push(entry(
                    node,
                    &json!({"kind":"unknown"}),
                    None,
                    None,
                    "Dynamic code or class evaluation",
                ));
            } else if access.as_ref().is_some_and(|(_, name)| name.is_none()) {
                consume(&callee, handled);
                effects.push(entry(
                    node,
                    &json!({"kind":"unknown"}),
                    None,
                    None,
                    "Computed callee may select a runtime installer",
                ));
            }
        }
    }
    if handled.contains(&crate::symbol_bindings::key(node)) {
        return effects;
    }
    if let Some((object, name)) = member(node, content) {
        if javascript
            && text(&object, content) == "Reflect"
            && bindings.unbound(&object, "Reflect")
            && name.as_ref().is_some_and(|name| {
                [
                    "get",
                    "has",
                    "ownKeys",
                    "getOwnPropertyDescriptor",
                    "getPrototypeOf",
                    "isExtensible",
                ]
                .contains(&name.as_str())
            })
        {
            consume(node, handled);
        } else if javascript
            && (name
                .as_ref()
                .is_some_and(|n| js_installers.contains(&n.as_str()))
                || text(&object, content) == "Object"
                    && (name.is_none() || name.as_deref() == Some("assign")))
        {
            effects.push(entry(
                node,
                &json!({"kind":"unknown"}),
                None,
                None,
                "Aliased property installer",
            ));
            consume(node, handled);
        } else if !javascript && name.as_deref() == Some("__dict__") {
            effects.push(entry(
                node,
                &target_scope(&object, content, receiver, false, bindings),
                None,
                None,
                "Indirect attribute dictionary",
            ));
            consume(node, handled);
        }
    }
    if kind == "identifier" && !bindings.is_binding(node) {
        let name = text(node, content);
        if (javascript
            && (js_installers.contains(&name) || ["Reflect", "eval", "Function"].contains(&name)))
            || (!javascript
                && (py_installers.contains(&name)
                    || ["exec", "eval", "globals", "locals", "vars"].contains(&name)))
        {
            effects.push(entry(
                node,
                &json!({"kind":"unknown"}),
                None,
                None,
                "Runtime installer or evaluation reference",
            ));
        }
    }
    effects
}

fn consume(node: &Node, handled: &mut std::collections::BTreeSet<crate::symbol_bindings::Key>) {
    handled.insert(crate::symbol_bindings::key(node));
    for child in named_children(node) {
        consume(&child, handled);
    }
}
