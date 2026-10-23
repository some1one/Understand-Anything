//! Swift containers, callable members, imports, and call relationships.
use super::*;
fn normalized(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}
fn identifier<'a>(n: &N<'a>) -> Option<&'a str> {
    if ["simple_identifier", "type_identifier", "identifier"].contains(&n.ty().as_str()) {
        return Some(n.text());
    }
    n.children().iter().find_map(identifier)
}
fn name<'a>(n: &N<'a>) -> Option<&'a str> {
    n.name().or_else(|| identifier(n))
}
fn visible(n: &N, parent: bool) -> bool {
    parent
        && !n.child("modifiers").is_some_and(|m| {
            m.of("visibility_modifier")
                .iter()
                .any(|v| ["private", "fileprivate"].contains(&normalized(v.text()).as_str()))
        })
}
fn kind(n: &N) -> String {
    n.field("declaration_kind")
        .map(|n| n.text().into())
        .unwrap_or_default()
}
fn container(n: &N) -> Option<String> {
    let name = normalized(n.name()?);
    Some(if kind(n) == "extension" {
        format!("extension {name}")
    } else {
        name
    })
}
fn callable(n: &N, a: &mut Value, name: &str) {
    let params = n
        .of("parameter")
        .iter()
        .filter_map(|p| {
            let p = p.field("name").unwrap_or_else(|| p.clone());
            fn last<'a>(n: &N<'a>) -> Option<&'a str> {
                n.children().iter().rev().find_map(last).or_else(|| {
                    (n.ty() == "simple_identifier" && n.text() != "_").then(|| n.text())
                })
            }
            last(&p).map(str::to_owned)
        })
        .collect();
    let children = n.children();
    let rt = children
        .iter()
        .position(|c| c.text() == "->")
        .and_then(|i| children[i + 1..].iter().find(|c| c.raw.is_named()))
        .filter(|c| !["function_body", "computed_property"].contains(&c.ty().as_str()))
        .map(|c| normalized(c.text()));
    push(a, "functions", function(n, name, params, rt.as_deref()));
}
fn properties(n: &N) -> Vec<String> {
    fn bound(n: &N, out: &mut Vec<String>) {
        if let Some(id) = n.field("bound_identifier") {
            out.push(id.text().into());
            return;
        }
        for c in n.children() {
            bound(&c, out);
        }
    }
    let mut out = vec![];
    for p in n.of("pattern") {
        bound(&p, &mut out);
    }
    if out.is_empty() {
        if let Some(p) = n.field("name") {
            bound(&p, &mut out);
        }
    }
    out
}
pub(super) fn import_node(n: &N, a: &mut Value) {
    if let Some(path) = n.child("identifier") {
        let parts: Vec<_> = path.text().split('.').filter(|p| !p.is_empty()).collect();
        if let (Some(first), Some(last)) = (parts.first(), parts.last()) {
            import(a, first, vec![(*last).into()], n.row());
        }
    }
}
fn members<'a>(
    body: &N<'a>,
    owner: &str,
    a: &mut Value,
    public: bool,
    methods: &mut Vec<String>,
    props: &mut Vec<String>,
    nested: &mut Vec<N<'a>>,
) {
    for m in body.children() {
        let ty = m.ty();
        let is_public = visible(&m, public);
        match ty.as_str() {
            "ERROR" | "if_config_declaration" => {
                members(&m, owner, a, public, methods, props, nested)
            }
            "function_declaration"
            | "protocol_function_declaration"
            | "init_declaration"
            | "deinit_declaration"
            | "subscript_declaration" => {
                let simple = match ty.as_str() {
                    "init_declaration" => Some("init"),
                    "deinit_declaration" => Some("deinit"),
                    "subscript_declaration" => Some("subscript"),
                    _ => name(&m),
                };
                if let Some(simple) = simple {
                    methods.push(simple.into());
                    let full = if ["init", "deinit"].contains(&simple) {
                        format!(
                            "{}.{simple}",
                            owner.strip_prefix("extension ").unwrap_or(owner)
                        )
                    } else {
                        simple.into()
                    };
                    callable(&m, a, &full);
                    if is_public && simple != "deinit" {
                        export(a, &full, m.row(), None);
                    }
                }
            }
            "property_declaration" | "protocol_property_declaration" => {
                for p in properties(&m) {
                    if is_public {
                        export(a, &p, m.row(), None);
                    }
                    props.push(p);
                }
            }
            "associatedtype_declaration" => {
                if let Some(p) = name(&m) {
                    props.push(p.into());
                    if is_public {
                        export(a, p, m.row(), None);
                    }
                }
            }
            "enum_entry" => {
                for child in m.children() {
                    if child.ty() == "simple_identifier" {
                        props.push(child.text().into());
                    }
                }
            }
            "class_declaration" | "protocol_declaration" => nested.push(m),
            _ => {}
        }
    }
}
pub(super) fn extract(root: &N, a: &mut Value) {
    walk(root, a, true);
}
fn walk(n: &N, a: &mut Value, parent_public: bool) {
    let public = visible(n, parent_public);
    match n.ty().as_str() {
        "import_declaration" => import_node(n, a),
        "function_declaration" => {
            if let Some(name) = name(n) {
                callable(n, a, name);
                if public {
                    export(a, name, n.row(), None);
                }
            }
        }
        "class_declaration" | "protocol_declaration" => {
            if let Some(name) = container(n) {
                let (mut methods, mut props, mut nested) = (vec![], vec![], vec![]);
                if let Some(body) = n.field("body") {
                    members(
                        &body,
                        &name,
                        a,
                        public,
                        &mut methods,
                        &mut props,
                        &mut nested,
                    );
                }
                push(a, "classes", class(n, &name, methods, props));
                if public && kind(n) != "extension" {
                    export(a, &name, n.row(), None);
                }
                for child in nested {
                    walk(&child, a, public);
                }
            }
        }
        "function_body" | "computed_property" | "class_body" | "protocol_body"
        | "enum_class_body" => {}
        _ => {
            for child in n.children() {
                walk(&child, a, parent_public);
            }
        }
    }
}
fn constructed(n: &N) -> Option<String> {
    n.child("constructed_type")
        .or_else(|| n.field("type"))
        .map(|n| normalized(n.text()))
        .or_else(|| identifier(n).map(str::to_owned))
}
fn callee(n: &N) -> Option<String> {
    for c in n.children() {
        if c.ty() == "call_suffix" {
            break;
        }
        match c.ty().as_str() {
            "simple_identifier" | "type_identifier" => return Some(c.text().into()),
            "navigation_expression" => {
                let text = normalized(c.text()).replace(['?', '!'], "");
                let parts: Vec<_> = text
                    .split('.')
                    .map(str::trim)
                    .filter(|p| !p.is_empty())
                    .collect();
                let first = *parts.first()?;
                return Some(
                    if first == "super"
                        || first.starts_with(|c: char| c.is_ascii_uppercase() || c == '_')
                    {
                        parts.join(".")
                    } else {
                        parts.last()?.to_string()
                    },
                );
            }
            "constructor_expression" => return constructed(&c),
            "user_type" | "member_type_identifier" => return Some(normalized(c.text())),
            _ => {}
        }
    }
    None
}
pub(super) fn calls(root: &N) -> Vec<Value> {
    fn visit(n: &N, owner: Option<&str>, caller: Option<&str>, out: &mut Vec<Value>) {
        match n.ty().as_str() {
            "class_declaration" | "protocol_declaration" => {
                let name = container(n);
                if let Some(body) = n.field("body") {
                    visit(&body, name.as_deref().or(owner), caller, out);
                }
                return;
            }
            "function_declaration" | "init_declaration" | "deinit_declaration" => {
                let name = if n.ty() == "function_declaration" {
                    name(n).map(str::to_owned)
                } else {
                    owner.map(|o| {
                        format!(
                            "{}.{}",
                            o.strip_prefix("extension ").unwrap_or(o),
                            if n.ty() == "init_declaration" {
                                "init"
                            } else {
                                "deinit"
                            }
                        )
                    })
                };
                if let (Some(name), Some(body)) = (name, n.field("body")) {
                    visit(&body, owner, Some(&name), out);
                }
                return;
            }
            "property_declaration" => {
                if let Some(body) = n.any(&["computed_property", "willset_didset_block"]) {
                    if let Some(name) = properties(n).first() {
                        visit(&body, owner, Some(name), out);
                        return;
                    }
                }
            }
            "call_expression" | "constructor_expression" => {
                if let Some(caller) = caller {
                    let callee = if n.ty() == "call_expression" {
                        callee(n)
                    } else {
                        constructed(n)
                    };
                    if let Some(callee) = callee {
                        out.push(json!({"caller":caller,"callee":callee,"lineNumber":n.row()}));
                    }
                }
            }
            _ => {}
        }
        for child in n.children() {
            visit(&child, owner, caller, out);
        }
    }
    let mut out = vec![];
    visit(root, None, None, &mut out);
    out
}
