//! Scala 2/3 declarations, selector imports, and call relationships.
use super::*;
const TYPES: &[&str] = &[
    "class_definition",
    "trait_definition",
    "object_definition",
    "package_object",
    "enum_definition",
];
const FUNCTIONS: &[&str] = &["function_definition", "function_declaration"];
const FIELDS: &[&str] = &[
    "val_definition",
    "var_definition",
    "val_declaration",
    "var_declaration",
];
fn name<'a>(n: &N<'a>) -> Option<&'a str> {
    n.child("identifier").map(|n| n.text())
}
fn visible(n: &N) -> bool {
    !n.child("modifiers")
        .and_then(|n| n.child("access_modifier"))
        .is_some_and(|n| n.text().starts_with("private"))
}
fn callable(n: &N, a: &mut Value, public: bool) {
    let Some(name) = name(n) else { return };
    let params = n
        .of("parameters")
        .iter()
        .flat_map(|p| p.of("parameter"))
        .filter_map(|p| p.child("identifier").map(|p| p.text().into()))
        .collect();
    let children = n.children();
    let rt = children
        .iter()
        .position(|c| c.ty() == ":")
        .and_then(|i| children[i + 1..].iter().find(|c| c.raw.is_named()))
        .map(|c| c.text());
    push(a, "functions", function(n, name, params, rt));
    if public && visible(n) {
        export(a, name, n.row(), None);
    }
}
fn extension(n: &N, a: &mut Value, public: bool) -> Vec<String> {
    let mut names = vec![];
    for f in n.of("function_definition") {
        if let Some(name) = name(&f) {
            names.push(name.into());
        }
        callable(&f, a, public);
    }
    names
}
fn type_definition(n: &N, a: &mut Value, parent: bool) {
    let Some(name) = name(n) else { return };
    let public = parent && visible(n);
    let mut properties = vec![];
    let mut methods = vec![];
    let case = n.child("case").is_some();
    for params in n.of("class_parameters") {
        for param in params.of("class_parameter") {
            if (case || param.any(&["val", "var"]).is_some())
                && let Some(id) = param.child("identifier")
            {
                properties.push(id.text().into());
            }
        }
    }
    if let Some(body) = n.any(&["template_body", "enum_body"]) {
        for m in body.children() {
            let ty = m.ty();
            if FUNCTIONS.contains(&ty.as_str()) {
                if let Some(name) = self::name(&m) {
                    methods.push(name.into());
                }
                callable(&m, a, public);
            } else if FIELDS.contains(&ty.as_str()) {
                if let Some(name) = self::name(&m) {
                    properties.push(name.into());
                    if public && visible(&m) {
                        export(a, name, m.row(), None);
                    }
                }
            } else if TYPES.contains(&ty.as_str()) {
                type_definition(&m, a, public);
            } else if ty == "extension_definition" {
                methods.extend(extension(&m, a, public));
            } else if ty == "enum_case_definitions" {
                for case in m.children() {
                    if let Some(id) = case.child("identifier") {
                        properties.push(id.text().into());
                    }
                }
            }
        }
    }
    push(a, "classes", class(n, name, methods, properties));
    if public {
        export(a, name, n.row(), None);
    }
}
fn selectors(n: &N, exported: bool) -> Vec<String> {
    let mut names = vec![];
    for c in n.children() {
        match c.ty().as_str() {
            "identifier" => names.push(c.text().into()),
            "namespace_wildcard" => names.push("*".into()),
            _ if c.raw.is_named() && c.child("wildcard").is_none() => {
                let ids = c.of("identifier");
                let selected = if exported { ids.last() } else { ids.first() };
                if let Some(id) = selected {
                    names.push(id.text().into());
                }
            }
            _ => {}
        }
    }
    names
}
pub(super) fn import_node(n: &N, a: &mut Value) {
    let children = n.children();
    for item in children.split(|c| c.ty() == ",") {
        let parts: Vec<_> = item
            .iter()
            .filter(|c| c.ty() == "identifier")
            .map(|c| c.text())
            .collect();
        if parts.is_empty() {
            continue;
        }
        let specs = if item.iter().any(|c| c.ty() == "namespace_wildcard") {
            vec!["*".into()]
        } else if let Some(s) = item.iter().find(|c| c.ty() == "namespace_selectors") {
            // An exclusion-only list does not import the whole package.
            selectors(s, false)
        } else {
            vec![parts.last().unwrap().to_string()]
        };
        import(a, &parts.join("."), specs, n.row());
    }
}
pub(super) fn extract(root: &N, a: &mut Value) {
    for n in root.children() {
        let ty = n.ty();
        if ["package_clause", "template_body"].contains(&ty.as_str()) {
            extract(&n, a);
        } else if ty == "import_declaration" {
            import_node(&n, a);
        } else if TYPES.contains(&ty.as_str()) {
            type_definition(&n, a, true);
        } else if FUNCTIONS.contains(&ty.as_str()) {
            callable(&n, a, true);
        } else if ty == "extension_definition" {
            extension(&n, a, true);
        } else if FIELDS.contains(&ty.as_str()) || ty == "given_definition" {
            if visible(&n)
                && let Some(name) = name(&n)
            {
                export(a, name, n.row(), None);
            }
        } else if ty == "export_declaration" {
            let names = n
                .child("namespace_selectors")
                .map(|s| selectors(&s, true))
                .unwrap_or_else(|| {
                    n.of("identifier")
                        .last()
                        .map(|id| vec![id.text().into()])
                        .unwrap_or_default()
                });
            for name in names {
                if name != "*" {
                    export(a, &name, n.row(), None);
                }
            }
        }
    }
}
fn callee(n: &N) -> Option<String> {
    match n.ty().as_str() {
        "call_expression" => {
            let mut target = n.children().into_iter().next()?;
            if target.ty() == "generic_function" {
                target = target.children().into_iter().next()?;
            }
            match target.ty().as_str() {
                "identifier" => Some(target.text().into()),
                "field_expression" => target.of("identifier").last().map(|id| id.text().into()),
                _ => None,
            }
        }
        "infix_expression" => {
            let ids = n.of("identifier");
            ids.get(1)
                .or_else(|| ids.first())
                .map(|id| id.text().into())
        }
        "instance_expression" => n
            .any(&["type_identifier", "identifier"])
            .map(|id| id.text().into()),
        _ => None,
    }
}
pub(super) fn calls(root: &N) -> Vec<Value> {
    fn visit(n: &N, caller: Option<&str>, out: &mut Vec<Value>) {
        let caller = if n.ty() == "function_definition" {
            name(n).or(caller)
        } else {
            caller
        };
        if let (Some(caller), Some(callee)) = (caller, callee(n)) {
            out.push(json!({"caller":caller,"callee":callee,"lineNumber":n.row()}));
        }
        for c in n.children() {
            visit(&c, caller, out);
        }
    }
    let mut out = vec![];
    visit(root, None, &mut out);
    out
}
