//! Structural extraction using the pinned pack's low-level node API.
use crate::{Error, Result, array, noncode, parsers};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};
#[derive(Clone)]
struct N<'a> {
    raw: tree_sitter_language_pack::Node,
    source: &'a str,
}
impl<'a> N<'a> {
    fn ty(&self) -> String {
        self.raw.kind()
    }
    fn text(&self) -> &'a str {
        self.source
            .get(self.raw.start_byte()..self.raw.end_byte())
            .unwrap_or("")
    }
    fn row(&self) -> usize {
        self.raw.start_position().row + 1
    }
    fn end(&self) -> usize {
        self.raw.end_position().row + 1
    }
    fn field(&self, k: &str) -> Option<Self> {
        self.raw.child_by_field_name(k).map(|raw| Self {
            raw,
            source: self.source,
        })
    }
    fn children(&self) -> Vec<Self> {
        (0..self.raw.child_count())
            .filter_map(|i| self.raw.child(i as u32))
            .map(|raw| Self {
                raw,
                source: self.source,
            })
            .collect()
    }
    fn child(&self, k: &str) -> Option<Self> {
        self.children().into_iter().find(|n| n.ty() == k)
    }
    fn any(&self, types: &[&str]) -> Option<Self> {
        self.children()
            .into_iter()
            .find(|n| types.contains(&n.ty().as_str()))
    }
    fn of(&self, k: &str) -> Vec<Self> {
        self.children()
            .into_iter()
            .filter(|n| n.ty() == k)
            .collect()
    }
    fn parent(&self) -> Option<Self> {
        self.raw.parent().map(|raw| Self {
            raw,
            source: self.source,
        })
    }
    fn name(&self) -> Option<&'a str> {
        self.field("name").map(|n| n.text())
    }
}
fn empty() -> Value {
    json!({"functions":[],"classes":[],"imports":[],"exports":[],"sections":null,"definitions":null,"services":null,"endpoints":null,"steps":null,"resources":null})
}
fn push(a: &mut Value, key: &str, v: Value) {
    a[key].as_array_mut().unwrap().push(v);
}
fn function(n: &N, name: &str, params: Vec<String>, rt: Option<&str>) -> Value {
    let mut v = json!({"name":name,"lineRange":[n.row(),n.end()],"params":params});
    if let Some(rt) = rt {
        v["returnType"] = json!(rt);
    }
    v
}
fn class(n: &N, name: &str, methods: Vec<String>, properties: Vec<String>) -> Value {
    json!({"name":name,"lineRange":[n.row(),n.end()],"methods":methods,"properties":properties})
}
fn export(a: &mut Value, name: &str, line: usize, default: Option<bool>) {
    let mut v = json!({"name":name,"lineNumber":line});
    if let Some(d) = default {
        v["isDefault"] = json!(d);
    }
    push(a, "exports", v);
}
fn import(a: &mut Value, source: &str, spec: Vec<String>, line: usize) {
    push(
        a,
        "imports",
        json!({"source":source,"specifiers":spec,"lineNumber":line}),
    );
}
fn unquote(s: &str) -> &str {
    let s = s.strip_prefix(['\'', '"', '`']).unwrap_or(s);
    s.strip_suffix(['\'', '"', '`']).unwrap_or(s)
}
fn params(node: Option<N>, lang: &str) -> Vec<String> {
    let Some(node) = node else { return vec![] };
    let mut out = vec![];
    for c in node.children() {
        let t = c.ty();
        let name = match lang {
            "typescript" => match t.as_str() {
                "required_parameter" | "optional_parameter" => c
                    .field("pattern")
                    .or_else(|| c.field("name"))
                    .or_else(|| c.child("identifier"))
                    .map(|n| n.text().to_owned()),
                "identifier" => Some(c.text().into()),
                "rest_pattern" | "rest_element" => {
                    c.child("identifier").map(|n| format!("...{}", n.text()))
                }
                _ => None,
            },
            "python" => match t.as_str() {
                "identifier" => Some(c.text().into()),
                "typed_parameter" | "default_parameter" | "typed_default_parameter" => {
                    c.child("identifier").map(|n| n.text().into())
                }
                "list_splat_pattern" => c.child("identifier").map(|n| format!("*{}", n.text())),
                "dictionary_splat_pattern" => {
                    c.child("identifier").map(|n| format!("**{}", n.text()))
                }
                _ => None,
            },
            "go" => {
                if t == "parameter_declaration" {
                    out.extend(c.of("identifier").iter().map(|n| n.text().into()));
                }
                None
            }
            "rust" => {
                if t == "parameter" {
                    c.field("pattern").map(|n| n.text().into())
                } else {
                    None
                }
            }
            "java" => {
                if t == "formal_parameter" {
                    c.name().map(str::to_owned)
                } else {
                    None
                }
            }
            "csharp" => {
                if t == "parameter" {
                    c.name().map(str::to_owned)
                } else {
                    None
                }
            }
            "ruby" => match t.as_str() {
                "identifier" => Some(c.text().into()),
                "optional_parameter" => c.name().map(str::to_owned),
                "splat_parameter" => c.name().map(|n| format!("*{n}")),
                "hash_splat_parameter" => c.name().map(|n| format!("**{n}")),
                "block_parameter" => c.name().map(|n| format!("&{n}")),
                _ => None,
            },
            _ => None,
        };
        if let Some(name) = name
            && !(lang == "python" && ["self", "cls"].contains(&name.as_str()))
        {
            out.push(name);
        }
    }
    if lang == "java" {
        out.extend(
            node.of("spread_parameter")
                .iter()
                .filter_map(N::name)
                .map(str::to_owned),
        );
    }
    out
}
fn ts_return(n: &N) -> Option<String> {
    n.field("return_type")
        .filter(|n| n.ty() == "type_annotation")
        .map(|n| {
            n.text()
                .strip_prefix(':')
                .map(str::trim)
                .unwrap_or(n.text())
                .into()
        })
}
fn ts_function(n: &N, a: &mut Value) {
    if let Some(name) = n.field("name").or_else(|| n.child("identifier")) {
        push(
            a,
            "functions",
            function(
                n,
                name.text(),
                params(
                    n.field("parameters")
                        .or_else(|| n.child("formal_parameters")),
                    "typescript",
                ),
                ts_return(n).as_deref(),
            ),
        );
    }
}
fn ts_class(n: &N, a: &mut Value) {
    if let Some(name) = n.any(&["type_identifier", "identifier"]) {
        let mut methods = vec![];
        let mut props = vec![];
        if let Some(body) = n.child("class_body") {
            for m in body.children() {
                if let Some(p) = m.child("property_identifier") {
                    match m.ty().as_str() {
                        "method_definition" | "abstract_method_signature" => methods.push(p.text().into()),
                        "public_field_definition" | "property_definition" => {
                            props.push(p.text().into())
                        }
                        _ => {}
                    }
                }
            }
        }
        push(a, "classes", class(n, name.text(), methods, props));
    }
}
fn ts_vars(n: &N, a: &mut Value) {
    for v in n.of("variable_declarator") {
        if let (Some(name), Some(value)) = (v.field("name"), v.field("value"))
            && ["arrow_function", "function_expression", "function"].contains(&value.ty().as_str())
        {
            push(
                a,
                "functions",
                function(
                    n,
                    name.text(),
                    params(
                        value
                            .field("parameters")
                            .or_else(|| value.child("formal_parameters")),
                        "typescript",
                    ),
                    ts_return(&value).as_deref(),
                ),
            );
        }
    }
}
fn typescript(root: &N, a: &mut Value) {
    let mut exported = BTreeSet::<String>::new();
    for n in root.children() {
        match n.ty().as_str() {
            "function_declaration" => ts_function(&n, a),
            "class_declaration" | "abstract_class_declaration" => ts_class(&n, a),
            "lexical_declaration" | "variable_declaration" => ts_vars(&n, a),
            "import_statement" => {
                if let Some(source) = n.child("string") {
                    let source = source
                        .child("string_fragment")
                        .map(|n| n.text())
                        .unwrap_or_else(|| unquote(source.text()));
                    let mut spec = vec![];
                    if let Some(clause) = n.child("import_clause") {
                        for c in clause.children() {
                            match c.ty().as_str() {
                                "named_imports" => {
                                    for s in c.of("import_specifier") {
                                        spec.push(
                                            s.field("alias")
                                                .or_else(|| s.field("name"))
                                                .map(|n| n.text())
                                                .unwrap_or(s.text())
                                                .into(),
                                        );
                                    }
                                }
                                "namespace_import" => {
                                    if let Some(id) = c.child("identifier") {
                                        spec.push(format!("* as {}", id.text()));
                                    }
                                }
                                "identifier" => spec.push(c.text().into()),
                                _ => {}
                            }
                        }
                    }
                    import(a, source, spec, n.row());
                }
            }
            "export_statement" => {
                let default = n.child("default").is_some();
                for c in n.children() {
                    let mut names = vec![];
                    match c.ty().as_str() {
                        "function_declaration" => {
                            ts_function(&c, a);
                            if let Some(name) = c.field("name").or_else(|| c.child("identifier")) {
                                names.push((name.text().to_owned(), Some(default)));
                            } else if default {
                                names.push(("default".into(), Some(true)));
                            }
                        }
                        "class_declaration" | "abstract_class_declaration" => {
                            ts_class(&c, a);
                            if let Some(name) = c.any(&["type_identifier", "identifier"])
                                && !exported.contains(name.text())
                            {
                                names.push((
                                    if default { "default" } else { name.text() }.into(),
                                    Some(default),
                                ));
                            }
                        }
                        "lexical_declaration" | "variable_declaration" => {
                            ts_vars(&c, a);
                            for d in c.of("variable_declarator") {
                                if let Some(name) = d.name() {
                                    names.push((name.into(), None));
                                }
                            }
                        }
                        "export_clause" => {
                            for s in c.of("export_specifier") {
                                names.push((
                                    s.field("alias")
                                        .or_else(|| s.field("name"))
                                        .map(|n| n.text())
                                        .unwrap_or(s.text())
                                        .into(),
                                    None,
                                ));
                            }
                        }
                        _ => {}
                    }
                    for (name, d) in names {
                        if exported.insert(name.clone()) {
                            export(a, &name, n.row(), d);
                        }
                    }
                }
            }
            _ => {}
        }
    }
}
fn py_unwrap(n: N) -> N {
    if n.ty() == "decorated_definition" {
        n.child("function_definition")
            .or_else(|| n.child("class_definition"))
            .unwrap_or(n)
    } else {
        n
    }
}
fn python(root: &N, a: &mut Value) {
    for outer in root.children() {
        let n = py_unwrap(outer.clone());
        match n.ty().as_str() {
            "function_definition" | "class_definition" => {
                if let Some(name) = n.name() {
                    if n.ty() == "function_definition" {
                        push(
                            a,
                            "functions",
                            function(
                                &n,
                                name,
                                params(n.field("parameters"), "python"),
                                n.field("return_type").map(|n| n.text()),
                            ),
                        );
                    } else {
                        let mut methods = vec![];
                        let mut props = vec![];
                        if let Some(body) = n.field("body") {
                            for m in body.children() {
                                let inner = py_unwrap(m.clone());
                                if inner.ty() == "function_definition"
                                    && let Some(name) = inner.name()
                                {
                                    methods.push(name.into());
                                }
                                let assignment = if m.ty() == "assignment" {
                                    Some(m)
                                } else {
                                    m.child("assignment")
                                };
                                if let Some(assign) = assignment
                                    && assign.child("type").is_some()
                                    && let Some(name) = assign.child("identifier")
                                {
                                    props.push(name.text().into());
                                }
                            }
                        }
                        push(a, "classes", class(&n, name, methods, props));
                    }
                    export(a, name, outer.row(), None);
                }
            }
            "import_statement" => {
                for d in n.of("dotted_name") {
                    import(a, d.text(), vec![d.text().into()], n.row());
                }
                for ali in n.of("aliased_import") {
                    if let Some(d) = ali.child("dotted_name") {
                        import(
                            a,
                            d.text(),
                            vec![
                                ali.child("identifier")
                                    .map(|n| n.text())
                                    .unwrap_or(d.text())
                                    .into(),
                            ],
                            n.row(),
                        );
                    }
                }
            }
            "import_from_statement" => {
                let module = n.field("module_name");
                let mut spec = vec![];
                for d in n.of("dotted_name") {
                    if module
                        .as_ref()
                        .is_none_or(|m| m.raw.start_byte() != d.raw.start_byte())
                    {
                        spec.push(d.text().into());
                    }
                }
                for ali in n.of("aliased_import") {
                    if let Some(id) = ali.child("identifier") {
                        spec.push(id.text().into());
                    }
                }
                if n.child("wildcard_import").is_some() {
                    spec.push("*".into());
                }
                import(a, module.map(|m| m.text()).unwrap_or(""), spec, n.row());
            }
            _ => {}
        }
    }
}
fn go_public(name: &str) -> bool {
    name.chars().next().is_some_and(|c| c.is_ascii_uppercase())
}
fn go(root: &N, a: &mut Value) {
    let mut receivers = BTreeMap::<String, Vec<String>>::new();
    for n in root.children() {
        match n.ty().as_str() {
            "function_declaration" | "method_declaration" => {
                if let Some(name) = n.name() {
                    let owner = if n.ty() == "method_declaration" {
                        crate::receivers::go(&n.raw, n.source)
                    } else { Some(String::new()) };
                    let mut extracted = function(&n, name, params(n.field("parameters"), "go"), n.field("result").map(|n| n.text()));
                    extracted["owner"] = json!(owner);
                    push(a, "functions", extracted);
                    if go_public(name) { export(a, name, n.row(), None); }
                    if let Some(owner) = owner.filter(|owner| !owner.is_empty()) {
                        receivers.entry(owner).or_default().push(name.into());
                    }
                }
            }
            "type_declaration" => {
                if let Some(spec) = n.child("type_spec")
                    && let (Some(name), Some(t)) = (spec.name(), spec.field("type"))
                    && ["struct_type", "interface_type"].contains(&t.ty().as_str())
                {
                    let mut methods = vec![];
                    let mut props = vec![];
                    if t.ty() == "struct_type" {
                        if let Some(list) = t.child("field_declaration_list") {
                            for f in list.of("field_declaration") {
                                props.extend(
                                    f.of("field_identifier").iter().map(|n| n.text().into()),
                                );
                            }
                        }
                    } else {
                        methods.extend(
                            t.of("method_elem")
                                .iter()
                                .filter_map(N::name)
                                .map(str::to_owned),
                        );
                    }
                    push(a, "classes", class(&n, name, methods, props));
                    if go_public(name) {
                        export(a, name, n.row(), None);
                    }
                }
            }
            "import_declaration" => {
                let container = n.child("import_spec_list").unwrap_or(n.clone());
                for spec in container.of("import_spec") {
                    if let Some(p) = spec.field("path") {
                        let source = p
                            .child("interpreted_string_literal_content")
                            .map(|n| n.text())
                            .unwrap_or_else(|| p.text().trim_matches('"'));
                        import(
                            a,
                            source,
                            vec![
                                spec.name()
                                    .unwrap_or_else(|| source.rsplit('/').next().unwrap_or(""))
                                    .into(),
                            ],
                            spec.row(),
                        );
                    }
                }
            }
            _ => {}
        }
    }
    append_methods(a, receivers);
}
fn append_methods(a: &mut Value, methods: BTreeMap<String, Vec<String>>) {
    for c in a["classes"].as_array_mut().unwrap() {
        if let Some(m) = methods.get(c["name"].as_str().unwrap_or("")) {
            c["methods"]
                .as_array_mut()
                .unwrap()
                .extend(m.iter().map(|s| json!(s)));
        }
    }
}
fn rust_public(n: &N) -> bool {
    n.child("visibility_modifier")
        .is_some_and(|v| v.text().starts_with("pub"))
}
fn rust_function(n: &N, a: &mut Value, owner: Option<&str>) {
    if let Some(name) = n.name() {
        let mut extracted = function(n, name, params(n.field("parameters"), "rust"), n.field("return_type").map(|n| n.text()));
        extracted["owner"] = json!(owner);
        push(a, "functions", extracted);
        if rust_public(n) {
            export(a, name, n.row(), None);
        }
    }
}
fn rust(root: &N, a: &mut Value) {
    let mut methods = BTreeMap::<String, Vec<String>>::new();
    for n in root.children() {
        match n.ty().as_str() {
            "function_item" => rust_function(&n, a, Some("")),
            "struct_item" | "enum_item" | "trait_item" => {
                if let Some(name) = n.name() {
                    let mut props = vec![];
                    let mut ms = vec![];
                    if let Some(body) = n.field("body").or_else(|| n.child("declaration_list")) {
                        match n.ty().as_str() {
                            "struct_item" => {
                                if body.ty() == "field_declaration_list" {
                                    for f in body.of("field_declaration") {
                                        if let Some(id) = f.child("field_identifier") {
                                            props.push(id.text().into());
                                        }
                                    }
                                }
                            }
                            "enum_item" => {
                                if body.ty() == "enum_variant_list" {
                                    props.extend(
                                        body.of("enum_variant")
                                            .iter()
                                            .filter_map(N::name)
                                            .map(str::to_owned),
                                    );
                                }
                            }
                            _ => {
                                for f in body.of("function_signature_item") {
                                    if let Some(id) = f.child("identifier") {
                                        ms.push(id.text().into());
                                    }
                                }
                                ms.extend(
                                    body.of("function_item")
                                        .iter()
                                        .filter_map(N::name)
                                        .map(str::to_owned),
                                );
                            }
                        }
                    }
                    push(a, "classes", class(&n, name, ms, props));
                    if rust_public(&n) {
                        export(a, name, n.row(), None);
                    }
                }
            }
            "impl_item" => {
                if let Some(body) = n.field("body") {
                    for f in body.of("function_item") {
                        let owner = crate::receivers::rust(&n.raw, n.source);
                        rust_function(&f, a, owner.as_deref());
                        if let (Some(t), Some(name)) = (n.field("type"), f.name()) {
                            methods
                                .entry(t.text().into())
                                .or_default()
                                .push(name.into());
                        }
                    }
                }
            }
            "use_declaration" => {
                if let Some(arg) = n.field("argument") {
                    match arg.ty().as_str() {
                        "scoped_identifier" => import(
                            a,
                            arg.field("path").map(|n| n.text()).unwrap_or(""),
                            vec![arg.name().unwrap_or("").into()],
                            n.row(),
                        ),
                        "scoped_use_list" => {
                            let spec = arg
                                .field("list")
                                .map(|l| {
                                    l.children()
                                        .iter()
                                        .filter(|c| {
                                            ["self", "identifier", "scoped_identifier"]
                                                .contains(&c.ty().as_str())
                                        })
                                        .map(|c| c.text().into())
                                        .collect()
                                })
                                .unwrap_or_default();
                            import(
                                a,
                                arg.field("path").map(|n| n.text()).unwrap_or(""),
                                spec,
                                n.row(),
                            );
                        }
                        "use_wildcard" => import(
                            a,
                            arg.child("scoped_identifier")
                                .map(|n| n.text())
                                .unwrap_or(""),
                            vec!["*".into()],
                            n.row(),
                        ),
                        _ => import(a, arg.text(), vec![arg.text().into()], n.row()),
                    }
                }
            }
            _ => {}
        }
    }
    append_methods(a, methods);
}
fn jpublic(n: &N, cs: bool) -> bool {
    if cs {
        n.of("modifier")
            .iter()
            .any(|m| m.children().iter().any(|c| c.text() == "public"))
    } else {
        n.child("modifiers")
            .is_some_and(|m| m.children().iter().any(|c| c.text() == "public"))
    }
}
fn java_class(n: &N, a: &mut Value, cs: bool) {
    let Some(name) = n.name() else { return };
    let interface = n.ty() == "interface_declaration";
    let mut methods = vec![];
    let mut props = vec![];
    if let Some(body) = n.field("body") {
        if interface {
            methods.extend(
                body.of("method_declaration")
                    .iter()
                    .filter_map(N::name)
                    .map(str::to_owned),
            );
            if cs {
                props.extend(
                    body.of("property_declaration")
                        .iter()
                        .filter_map(N::name)
                        .map(str::to_owned),
                );
            } else {
                for f in body.of("constant_declaration") {
                    props.extend(
                        f.of("variable_declarator")
                            .iter()
                            .filter_map(N::name)
                            .map(str::to_owned),
                    );
                }
            }
        } else {
            let members: Vec<_> = body.children().into_iter().flat_map(|member| {
                if !cs && member.ty() == "enum_body_declarations" {
                    member.children()
                } else { vec![member] }
            }).collect();
            for m in members {
                match m.ty().as_str() {
                    "method_declaration" | "constructor_declaration" => {
                        if let Some(name) = m.name() {
                            methods.push(name.into());
                            let rt = if m.ty() == "constructor_declaration" {
                                None
                            } else {
                                m.field(if cs { "returns" } else { "type" })
                                    .map(|n| n.text())
                            };
                            push(
                                a,
                                "functions",
                                function(
                                    &m,
                                    name,
                                    params(
                                        m.field("parameters"),
                                        if cs { "csharp" } else { "java" },
                                    ),
                                    rt,
                                ),
                            );
                            if jpublic(&m, cs) {
                                export(a, name, m.row(), None);
                            }
                        }
                    }
                    "property_declaration" if cs => {
                        if let Some(name) = m.name() {
                            props.push(name.into());
                            if jpublic(&m, cs) {
                                export(a, name, m.row(), None);
                            }
                        }
                    }
                    "field_declaration" => {
                        let decl = if cs {
                            m.child("variable_declaration")
                        } else {
                            Some(m.clone())
                        };
                        if let Some(decl) = decl {
                            for d in decl.of("variable_declarator") {
                                let name = if cs {
                                    d.child("identifier").map(|n| n.text())
                                } else {
                                    d.name()
                                };
                                if let Some(name) = name {
                                    props.push(name.into());
                                    if jpublic(&m, cs) {
                                        export(a, name, m.row(), None);
                                    }
                                }
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
    }
    push(a, "classes", class(n, name, methods, props));
    if jpublic(n, cs) {
        export(a, name, n.row(), None);
    }
}
fn java(root: &N, a: &mut Value, cs: bool, namespace: bool) {
    for n in root.children() {
        match n.ty().as_str() {
            "class_declaration" | "interface_declaration" | "record_declaration" => java_class(&n, a, cs),
            "enum_declaration" if !cs => java_class(&n, a, cs),
            "struct_declaration" if cs => java_class(&n, a, cs),
            "namespace_declaration" if cs => {
                if let Some(body) = n.field("body") {
                    java(&body, a, true, true);
                }
            }
            "using_directive" if cs && !namespace => {
                let source = if n.child("=").is_some() {
                    n.child("qualified_name")
                } else {
                    n.child("qualified_name").or_else(|| n.child("identifier"))
                };
                if let Some(s) = source {
                    import(
                        a,
                        s.text(),
                        vec![s.text().rsplit('.').next().unwrap_or("").into()],
                        n.row(),
                    );
                }
            }
            "import_declaration" if !cs => {
                if let Some(s) = n.child("scoped_identifier") {
                    import(
                        a,
                        s.text(),
                        vec![
                            if n.child("asterisk").is_some() {
                                "*"
                            } else {
                                s.text().rsplit('.').next().unwrap_or("")
                            }
                            .into(),
                        ],
                        n.row(),
                    );
                }
            }
            _ => {}
        }
    }
}
fn kt_name<'a>(n: &N<'a>) -> Option<&'a str> {
    n.any(&["simple_identifier", "identifier", "type_identifier"])
        .map(|n| n.text())
}
fn kt_public(n: &N) -> bool {
    n.child("modifiers")
        .and_then(|m| m.child("visibility_modifier"))
        .is_none_or(|v| v.text() != "private")
}
fn kt_function(n: &N, a: &mut Value) {
    if let Some(name) = kt_name(n) {
        let p = n
            .child("function_value_parameters")
            .map(|p| {
                p.of("parameter")
                    .iter()
                    .filter_map(|p| {
                        p.child("simple_identifier")
                            .or_else(|| p.child("identifier"))
                    })
                    .map(|n| n.text().into())
                    .collect()
            })
            .unwrap_or_default();
        let mut after_params = false;
        let mut after_colon = false;
        let mut rt = None;
        for c in n.children() {
            if c.ty() == "function_value_parameters" {
                after_params = true;
                continue;
            }
            if after_params && c.ty() == ":" {
                after_colon = true;
                continue;
            }
            if after_colon && c.raw.is_named() {
                rt = Some(c.text());
                break;
            }
        }
        push(a, "functions", function(n, name, p, rt));
        if kt_public(n) {
            export(a, name, n.row(), None);
        }
    }
}
fn kt_import(n: &N, a: &mut Value) {
    let mut parts: Vec<String> = if let Some(q) = n.child("qualified_identifier") {
        q.of("identifier").iter().map(|n| n.text().into()).collect()
    } else if let Some(q) = n.child("identifier") {
        let mut p: Vec<String> = q
            .children()
            .iter()
            .filter(|c| ["simple_identifier", "identifier"].contains(&c.ty().as_str()))
            .map(|n| n.text().into())
            .collect();
        if p.is_empty() {
            p.push(q.text().into());
        }
        p
    } else {
        vec![]
    };
    if parts.is_empty() {
        return;
    }
    let source = parts.join(".");
    let mut spec = parts.pop().unwrap();
    let mut wildcard = n.child("wildcard_import").is_some();
    if let Some(alias) = n.child("import_alias") {
        if let Some(name) = alias
            .child("type_identifier")
            .or_else(|| alias.child("simple_identifier"))
            .or_else(|| alias.child("identifier"))
        {
            spec = name.text().into();
        }
    } else {
        let mut saw = false;
        for c in n.children() {
            if c.ty() == "*" {
                wildcard = true;
            }
            if c.ty() == "as" {
                saw = true;
            } else if saw
                && ["identifier", "type_identifier", "simple_identifier"].contains(&c.ty().as_str())
            {
                spec = c.text().into();
                saw = false;
            }
        }
    }
    if wildcard {
        spec = "*".into();
    }
    import(a, &source, vec![spec], n.row());
}
fn kotlin(root: &N, a: &mut Value) {
    for n in root.children() {
        match n.ty().as_str() {
            "import" => kt_import(&n, a),
            "import_list" => {
                for h in n.children() {
                    if ["import_header", "import"].contains(&h.ty().as_str()) {
                        kt_import(&h, a);
                    }
                }
            }
            "function_declaration" => kt_function(&n, a),
            "class_declaration" | "object_declaration" => {
                if let Some(name) = kt_name(&n) {
                    let mut methods = vec![];
                    let mut props = vec![];
                    if n.ty() == "class_declaration"
                        && let Some(primary) = n.child("primary_constructor")
                    {
                        let container = primary.child("class_parameters").unwrap_or(primary);
                        for p in container.of("class_parameter") {
                            if (p.any(&["val", "var"]).is_some()
                                || p.child("binding_pattern_kind")
                                    .is_some_and(|b| b.any(&["val", "var"]).is_some()))
                                && let Some(id) = p
                                    .child("simple_identifier")
                                    .or_else(|| p.child("identifier"))
                            {
                                props.push(id.text().into());
                            }
                        }
                    }
                    if let Some(body) = n.child("class_body") {
                        for m in body.children() {
                            match m.ty().as_str() {
                                "function_declaration" => {
                                    if let Some(name) = kt_name(&m) {
                                        methods.push(name.into());
                                        kt_function(&m, a);
                                    }
                                }
                                "property_declaration" => {
                                    if let Some(v) = m.child("variable_declaration")
                                        && let Some(name) = v
                                            .child("simple_identifier")
                                            .or_else(|| v.child("identifier"))
                                    {
                                        props.push(name.text().into());
                                        if kt_public(&m) {
                                            export(a, name.text(), m.row(), None);
                                        }
                                    }
                                }
                                "object_declaration" => {
                                    if let Some(name) = kt_name(&m) {
                                        props.push(name.into());
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    push(a, "classes", class(&n, name, methods, props));
                    if kt_public(&n) {
                        export(a, name, n.row(), None);
                    }
                }
            }
            _ => {}
        }
    }
}
fn php_function(n: &N, a: &mut Value) {
    if let Some(name) = n.child("name") {
        let p = n
            .child("formal_parameters")
            .map(|p| {
                p.of("simple_parameter")
                    .iter()
                    .filter_map(|p| p.child("variable_name"))
                    .map(|n| n.text().into())
                    .collect()
            })
            .unwrap_or_default();
        let mut colon = false;
        let mut rt = None;
        for c in n.children() {
            if c.ty() == ":" {
                colon = true;
            } else if colon
                && [
                    "primitive_type",
                    "named_type",
                    "optional_type",
                    "union_type",
                ]
                .contains(&c.ty().as_str())
            {
                rt = Some(c.text());
                break;
            }
        }
        push(a, "functions", function(n, name.text(), p, rt));
    }
}
fn php_use_name(n: &N, prefix: &str) -> String {
    if let Some(q) = n.child("qualified_name") {
        q.text().into()
    } else if let Some(name) = n.child("name") {
        if prefix.is_empty() {
            name.text().into()
        } else {
            format!("{prefix}\\{}", name.text())
        }
    } else {
        n.text().into()
    }
}
fn php(root: &N, a: &mut Value) {
    for n in root.children() {
        match n.ty().as_str() {
            "function_definition" => {
                php_function(&n, a);
                export(
                    a,
                    n.child("name").map(|n| n.text()).unwrap_or(""),
                    n.row(),
                    None,
                );
            }
            "class_declaration" | "interface_declaration" => {
                let name = n.child("name").map(|n| n.text()).unwrap_or("");
                if !name.is_empty() {
                    let mut methods = vec![];
                    let mut props = vec![];
                    if let Some(body) = n.child("declaration_list") {
                        for m in body.children() {
                            if m.ty() == "method_declaration"
                                && let Some(name) = m.child("name")
                            {
                                methods.push(name.text().into());
                                if n.ty() == "class_declaration" {
                                    php_function(&m, a);
                                }
                            } else if n.ty() == "class_declaration"
                                && m.ty() == "property_declaration"
                                && let Some(v) = m
                                    .child("property_element")
                                    .and_then(|p| p.child("variable_name"))
                            {
                                props.push(
                                    v.child("name")
                                        .map(|n| n.text())
                                        .unwrap_or_else(|| v.text().trim_start_matches('$'))
                                        .into(),
                                );
                            }
                        }
                    }
                    push(a, "classes", class(&n, name, methods, props));
                }
                export(a, name, n.row(), None);
            }
            "namespace_definition" => {
                if let Some(body) = n.child("compound_statement") {
                    php(&body, a);
                }
            }
            "namespace_use_declaration" => {
                if let Some(group) = n.child("namespace_use_group") {
                    let prefix = n.child("namespace_name").map(|n| n.text()).unwrap_or("");
                    let spec: Vec<_> = group
                        .of("namespace_use_clause")
                        .iter()
                        .map(|c| {
                            php_use_name(c, prefix)
                                .rsplit('\\')
                                .next()
                                .unwrap_or("")
                                .to_owned()
                        })
                        .collect();
                    let source = if prefix.is_empty() {
                        spec.join(", ")
                    } else {
                        format!("{prefix}\\{{{}}}", spec.join(", "))
                    };
                    import(a, &source, spec, n.row());
                } else {
                    for c in n.of("namespace_use_clause") {
                        let source = php_use_name(&c, "");
                        let spec = source.rsplit('\\').next().unwrap_or("").to_owned();
                        import(a, &source, vec![spec], n.row());
                    }
                }
            }
            _ => {}
        }
    }
}
const RUBY_IMPORTS: &[&str] = &["require", "require_relative"];
const RUBY_ATTRS: &[&str] = &["attr_accessor", "attr_reader", "attr_writer"];
fn ruby_name(n: &N) -> Option<String> {
    n.name().map(|s| {
        if n.ty() == "singleton_method" {
            format!("self.{s}")
        } else {
            s.into()
        }
    })
}
fn ruby_function(n: &N, a: &mut Value) {
    if let Some(name) = ruby_name(n) {
        push(
            a,
            "functions",
            function(n, &name, params(n.field("parameters"), "ruby"), None),
        );
    }
}
fn ruby(root: &N, a: &mut Value) {
    for n in root.children() {
        match n.ty().as_str() {
            "method" | "singleton_method" => {
                ruby_function(&n, a);
                export(
                    a,
                    &ruby_name(&n).unwrap_or_else(|| {
                        if n.ty() == "singleton_method" {
                            "self.".into()
                        } else {
                            "".into()
                        }
                    }),
                    n.row(),
                    None,
                );
            }
            "class" | "module" => {
                let name = n.name().unwrap_or("");
                if !name.is_empty() {
                    let mut methods = vec![];
                    let mut props = vec![];
                    if let Some(body) = n.field("body") {
                        for m in body.children() {
                            match m.ty().as_str() {
                                "method" | "singleton_method" => {
                                    if let Some(name) = ruby_name(&m) {
                                        methods.push(name);
                                        ruby_function(&m, a);
                                    }
                                }
                                "call" => {
                                    if m.field("method")
                                        .is_some_and(|n| RUBY_ATTRS.contains(&n.text()))
                                        && let Some(args) = m.field("arguments")
                                    {
                                        props.extend(args.of("simple_symbol").iter().map(|s| {
                                            s.text().strip_prefix(':').unwrap_or(s.text()).into()
                                        }));
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    push(a, "classes", class(&n, name, methods, props));
                }
                export(a, name, n.row(), None);
            }
            "call" => {
                if n.field("method")
                    .is_some_and(|n| RUBY_IMPORTS.contains(&n.text()))
                    && let Some(s) = n.field("arguments").and_then(|a| a.child("string"))
                {
                    let source = s
                        .child("string_content")
                        .map(|n| n.text())
                        .unwrap_or_else(|| unquote(s.text()));
                    import(a, source, vec![source.into()], n.row());
                }
            }
            _ => {}
        }
    }
}
fn cpp_unwrap<'a>(n: &N<'a>) -> Option<&'a str> {
    if ["identifier", "field_identifier"].contains(&n.ty().as_str()) {
        Some(n.text())
    } else if let Some(d) = n.field("declarator") {
        cpp_unwrap(&d)
    } else {
        n.child("identifier")
            .or_else(|| n.child("field_identifier"))
            .map(|n| n.text())
    }
}
fn cpp_name<'a>(n: &N<'a>) -> Option<(&'a str, Option<&'a str>)> {
    crate::receivers::cpp_declarator(&n.raw, n.source).or_else(|| {
        let d = n.field("declarator")?;
        if d.ty() == "qualified_identifier" {
            Some((d.name().unwrap_or(d.text()), d.field("scope").map(|n| n.text())))
        } else {
            Some((d.text(), None))
        }
    })
}
fn cpp_params(n: Option<N>) -> Vec<String> {
    n.map(|p| {
        p.of("parameter_declaration")
            .iter()
            .filter_map(|p| p.field("declarator").and_then(|d| cpp_unwrap(&d)))
            .map(str::to_owned)
            .collect()
    })
    .unwrap_or_default()
}
fn cpp_class(n: &N, a: &mut Value) {
    let Some(class_name) = n.name() else { return };
    let mut methods = vec![];
    let mut props = vec![];
    if let Some(body) = n
        .field("body")
        .filter(|b| b.ty() == "field_declaration_list")
    {
        let mut access = if n.ty() == "struct_specifier" {
            "public"
        } else {
            "private"
        };
        for m in body.children() {
            if m.ty() == "access_specifier" {
                if let Some(c) = m.children().first() {
                    access = c.text();
                }
                continue;
            }
            if let Some(d) = m.field("declarator") {
                if m.ty() == "field_declaration" {
                    if d.ty() == "function_declarator" {
                        if let Some((name, _)) = cpp_name(&d) {
                            methods.push(name.into());
                            if access == "public" {
                                export(a, name, m.row(), None);
                            }
                        }
                    } else if let Some(name) = cpp_unwrap(&d) {
                        props.push(name.into());
                    }
                }
                if m.ty() == "function_definition"
                    && d.ty() == "function_declarator"
                    && let Some((name, _)) = cpp_name(&d)
                {
                    methods.push(name.into());
                    let mut extracted = function(&m, name, cpp_params(d.field("parameters")), m.field("type").map(|n| n.text()));
                    extracted["owner"] = json!(class_name);
                    push(a, "functions", extracted);
                    if access == "public" {
                        export(a, name, m.row(), None);
                    }
                }
            }
        }
    }
    push(a, "classes", class(n, class_name, methods, props));
    export(a, class_name, n.row(), None);
}
fn cpp_walk(root: &N, a: &mut Value, methods: &mut BTreeMap<String, Vec<String>>) {
    for n in root.children() {
        match n.ty().as_str() {
            "preproc_include" => {
                if let Some(p) = n.field("path") {
                    let source = match p.ty().as_str() {
                        "system_lib_string" => p.text().trim_matches(['<', '>']),
                        "string_literal" => p
                            .child("string_content")
                            .map(|n| n.text())
                            .unwrap_or_else(|| p.text().trim_matches('"')),
                        _ => p.text(),
                    };
                    import(a, source, vec![source.into()], n.row());
                }
            }
            "class_specifier" | "struct_specifier" => cpp_class(&n, a),
            "declaration" => {
                if let Some(c) = n.child("class_specifier") {
                    cpp_class(&c, a);
                }
                if let Some(c) = n.child("struct_specifier") {
                    cpp_class(&c, a);
                }
            }
            "namespace_definition" => {
                if let Some(b) = n.child("declaration_list") {
                    cpp_walk(&b, a, methods);
                }
            }
            "function_definition" => {
                if let Some(d) = n
                    .field("declarator")
                    .filter(|d| d.ty() == "function_declarator")
                    && let Some((name, q)) = cpp_name(&d)
                {
                    let mut extracted = function(&n, name, cpp_params(d.field("parameters")), n.field("type").map(|n| n.text()));
                    extracted["owner"] = json!(q.unwrap_or(""));
                    push(a, "functions", extracted);
                    if let Some(q) = q {
                        methods.entry(q.into()).or_default().push(name.into());
                    }
                    if n.child("storage_class_specifier")
                        .is_none_or(|s| s.text() != "static")
                    {
                        export(a, name, n.row(), None);
                    }
                }
            }
            _ => {}
        }
    }
}
fn cpp(root: &N, a: &mut Value) {
    let mut methods = BTreeMap::new();
    cpp_walk(root, a, &mut methods);
    for c in a["classes"].as_array_mut().unwrap() {
        if let Some(ms) = methods.get(c["name"].as_str().unwrap_or("")) {
            for m in ms {
                let value = json!(m);
                if !c["methods"].as_array().unwrap().contains(&value) {
                    c["methods"].as_array_mut().unwrap().push(value);
                }
            }
        }
    }
}
fn call_graph(root: &N, lang: &str) -> Vec<Value> {
    fn walk(n: &N, lang: &str, stack: &mut Vec<String>, out: &mut Vec<Value>) {
        let t = n.ty();
        let name = match lang {
            "typescript" => match t.as_str() {
                "function_declaration" => n
                    .field("name")
                    .or_else(|| n.child("identifier"))
                    .map(|n| n.text().into()),
                "method_definition" => n.child("property_identifier").map(|n| n.text().into()),
                "arrow_function" | "function_expression" => n
                    .parent()
                    .filter(|p| p.ty() == "variable_declarator")
                    .and_then(|p| p.name())
                    .map(str::to_owned),
                _ => None,
            },
            "python" => {
                if t == "function_definition" {
                    n.name().map(str::to_owned)
                } else {
                    None
                }
            }
            "go" => {
                if ["function_declaration", "method_declaration"].contains(&t.as_str()) {
                    n.name().map(str::to_owned)
                } else {
                    None
                }
            }
            "rust" => {
                if t == "function_item" {
                    n.name().map(str::to_owned)
                } else {
                    None
                }
            }
            "java" | "csharp" => {
                if ["method_declaration", "constructor_declaration"].contains(&t.as_str()) {
                    n.name().map(str::to_owned)
                } else {
                    None
                }
            }
            "kotlin" => {
                if t == "function_declaration" {
                    kt_name(n).map(str::to_owned)
                } else {
                    None
                }
            }
            "php" => {
                if ["function_definition", "method_declaration"].contains(&t.as_str()) {
                    n.child("name").map(|n| n.text().into())
                } else {
                    None
                }
            }
            "ruby" => {
                if ["method", "singleton_method"].contains(&t.as_str()) {
                    ruby_name(n)
                } else {
                    None
                }
            }
            "c" | "cpp" => {
                if t == "function_definition" {
                    n.field("declarator")
                        .filter(|d| d.ty() == "function_declarator")
                        .and_then(|d| cpp_name(&d).map(|v| v.0.to_owned()))
                } else {
                    None
                }
            }
            _ => None,
        }
        .filter(|s: &String| !s.is_empty());
        let pushed = name.is_some();
        if let Some(name) = name {
            stack.push(name);
        }
        if let Some(caller) = stack.last() {
            let callee = match lang {
                "typescript" | "go" => {
                    if t == "call_expression" {
                        n.field("function").map(|n| n.text().into())
                    } else {
                        None
                    }
                }
                "python" => {
                    if t == "call" {
                        n.field("function")
                            .or_else(|| n.any(&["identifier", "attribute"]))
                            .map(|n| n.text().into())
                    } else {
                        None
                    }
                }
                "rust" | "c" | "cpp" => {
                    if t == "call_expression" {
                        n.children().first().map(|first| {
                            if first.ty() == "field_expression" {
                                let field = first.field("field");
                                let value = first.field("value");
                                if lang == "rust" {
                                    if let (Some(f), Some(v)) = (field, value) {
                                        return format!("{}.{}", v.text(), f.text());
                                    }
                                } else if let Some(f) = field {
                                    return f.text().into();
                                }
                            }
                            first.text().into()
                        })
                    } else {
                        None
                    }
                }
                "java" => match t.as_str() {
                    "method_invocation" => n.name().map(|name| {
                        n.field("object")
                            .map(|obj| format!("{}.{name}", obj.text()))
                            .unwrap_or_else(|| name.into())
                    }),
                    "object_creation_expression" => {
                        n.field("type").map(|t| format!("new {}", t.text()))
                    }
                    _ => None,
                },
                "csharp" => match t.as_str() {
                    "invocation_expression" => n.field("function").map(|n| n.text().into()),
                    "object_creation_expression" => n
                        .child("identifier")
                        .or_else(|| n.child("generic_name"))
                        .map(|t| format!("new {}", t.text())),
                    _ => None,
                },
                "kotlin" => {
                    if t == "call_expression" {
                        n.children()
                            .first()
                            .and_then(|first| match first.ty().as_str() {
                                "simple_identifier" | "identifier" => Some(first.text().into()),
                                "navigation_expression" => {
                                    let mut last = None;
                                    for c in first.children() {
                                        if ["simple_identifier", "identifier"]
                                            .contains(&c.ty().as_str())
                                        {
                                            last = Some(c.text().into());
                                        } else if c.ty() == "navigation_suffix"
                                            && let Some(id) = c
                                                .child("simple_identifier")
                                                .or_else(|| c.child("identifier"))
                                        {
                                            last = Some(id.text().into());
                                        }
                                    }
                                    last
                                }
                                _ => None,
                            })
                    } else {
                        None
                    }
                }
                "php" => match t.as_str() {
                    "function_call_expression" => n.child("name").map(|n| n.text().into()),
                    "member_call_expression" => n.child("name").map(|name| {
                        n.children()
                            .first()
                            .map(|recv| format!("{}->{}", recv.text(), name.text()))
                            .unwrap_or_else(|| name.text().into())
                    }),
                    "scoped_call_expression" => {
                        let c = n.children();
                        if c.len() > 2 && c[2].ty() == "name" {
                            Some(format!("{}::{}", c[0].text(), c[2].text()))
                        } else {
                            None
                        }
                    }
                    _ => None,
                },
                "ruby" => {
                    if t == "call" {
                        n.field("method")
                            .filter(|m| {
                                !RUBY_IMPORTS.contains(&m.text()) && !RUBY_ATTRS.contains(&m.text())
                            })
                            .map(|m| {
                                n.field("receiver")
                                    .map(|r| format!("{}.{}", r.text(), m.text()))
                                    .unwrap_or_else(|| m.text().into())
                            })
                    } else if t == "identifier"
                        && n.parent().is_some_and(|p| p.ty() == "body_statement")
                    {
                        Some(n.text().into())
                    } else {
                        None
                    }
                }
                _ => None,
            };
            if let Some(callee) = callee {
                out.push(json!({"caller":caller,"callee":callee,"lineNumber":n.row()}));
            }
        }
        for c in n.children() {
            walk(&c, lang, stack, out);
        }
        if pushed {
            stack.pop();
        }
    }
    let mut out = vec![];
    walk(root, lang, &mut vec![], &mut out);
    out
}
fn normalized_lang(lang: &str) -> &str {
    if ["tsx", "javascript"].contains(&lang) {
        "typescript"
    } else {
        lang
    }
}
pub fn analyze_file(path: &str, content: &str) -> Option<Value> {
    let lang = parsers::detect_registry_language(path)?;
    if !parsers::LANGUAGES.contains(&lang.as_str()) {
        return noncode::analyze(&lang, content).map(|v| {
            let mut result = empty();
            result
                .as_object_mut()
                .unwrap()
                .extend(v.as_object().unwrap().clone());
            result
        });
    }
    let mut a = empty();
    if let Ok(tree) = parsers::parse(&lang, content) {
        let n = N {
            raw: tree.root_node(),
            source: content,
        };
        extract_tree_structure(&n, &lang, &mut a);
    }
    Some(a)
}
/// Batch extraction shares one syntax tree between both deterministic passes.
/// Keep the existing permissive fallback contract; strict evidence uses its own API.
pub fn analyze_file_full(path: &str, content: &str) -> (Option<Value>, Option<Vec<Value>>) {
    let Some(lang) = parsers::detect_registry_language(path) else { return (None, None) };
    if !parsers::LANGUAGES.contains(&lang.as_str()) {
        return (analyze_file(path, content), None);
    }
    let mut structure = empty();
    let mut calls = vec![];
    if let Ok(tree) = parsers::parse(&lang, content) {
        let root = N { raw: tree.root_node(), source: content };
        extract_tree_structure(&root, &lang, &mut structure);
        calls = call_graph(&root, normalized_lang(&lang));
    }
    (Some(structure), Some(calls))
}

fn extract_tree_structure(n: &N, lang: &str, a: &mut Value) {
    match normalized_lang(lang) {
        "typescript" => typescript(n, a),
        "python" => python(n, a),
        "go" => go(n, a),
        "rust" => rust(n, a),
        "java" => java(n, a, false, false),
        "kotlin" => kotlin(n, a),
        "csharp" => java(n, a, true, false),
        "php" => php(n, a),
        "ruby" => ruby(n, a),
        "c" | "cpp" => cpp(n, a),
        _ => {}
    }
}

/// Evidence for destructive comparisons: recovered syntax errors and unavailable
/// grammars must never be interpreted as a successful file with zero symbols.
pub fn analyze_file_strict(path: &str, content: &str) -> Value {
    let Some(lang) = parsers::detect_registry_language(path)
        .filter(|lang| parsers::LANGUAGES.contains(&lang.as_str())) else {
        return json!({"status":"unsupported","structure":null,"leafTexts":[]});
    };
    let tree = match parsers::parse(&lang, content) {
        Ok(tree) => tree,
        Err(error) => return json!({"status":"failed","structure":null,"leafTexts":[],"reason":error.to_string()}),
    };
    let root = N { raw: tree.root_node(), source: content };
    if root.raw.has_error() {
        return json!({"status":"failed","structure":null,"leafTexts":[],"reason":"syntax errors"});
    }
    let mut structure = empty();
    extract_tree_structure(&root, &lang, &mut structure);
    let scopes = crate::symbol_scopes::collect(root.raw.clone(), content, &lang, &structure);
    let mut leaves = BTreeSet::new();
    let mut pending = vec![root];
    while let Some(node) = pending.pop() {
        if node.raw.child_count() == 0 { leaves.insert(node.text()); }
        else { pending.extend(node.children()); }
    }
    json!({"status":"succeeded","language":lang,"structure":structure,"leafTexts":leaves,"declarationScopes":scopes})
}

pub fn extract_call_graph(path: &str, content: &str) -> Option<Vec<Value>> {
    let lang = parsers::detect_registry_language(path)?;
    if !parsers::LANGUAGES.contains(&lang.as_str()) {
        return None;
    }
    Some(
        parsers::parse(&lang, content)
            .map(|tree| {
                call_graph(
                    &N {
                        raw: tree.root_node(),
                        source: content,
                    },
                    normalized_lang(&lang),
                )
            })
            .unwrap_or_default(),
    )
}
pub fn count_lines(content: &str) -> (usize, usize) {
    let lines: Vec<_> = content.split('\n').collect();
    (
        lines.len() - usize::from(content.ends_with('\n')),
        lines.iter().filter(|s| !s.trim().is_empty()).count(),
    )
}
pub fn build_result(
    file: &Value,
    total: usize,
    nonempty: usize,
    analysis: Option<&Value>,
    calls: Option<&[Value]>,
    imports: &Value,
) -> Value {
    let mut base = json!({"path":file["path"],"language":file["language"],"fileCategory":file["fileCategory"],"totalLines":total,"nonEmptyLines":nonempty,"metrics":{}});
    let Some(a) = analysis else { return base };
    for key in [
        "functions",
        "classes",
        "exports",
        "sections",
        "definitions",
        "services",
        "endpoints",
        "steps",
        "resources",
    ] {
        let values:Vec<_>=array(a,key).iter().map(|n|match key{
            "functions"=>{let mut function = json!({"name":n["name"],"startLine":n["lineRange"][0],"endLine":n["lineRange"][1],"params":array(n,"params")}); if let Some(owner) = n.get("owner") { function["owner"] = owner.clone(); } function},
            "classes"=>json!({"name":n["name"],"startLine":n["lineRange"][0],"endLine":n["lineRange"][1],"methods":array(n,"methods"),"properties":array(n,"properties")}),
            "exports"=>json!({"name":n["name"],"line":n["lineNumber"],"isDefault":n["isDefault"]==true}),
            "sections"=>json!({"heading":n["name"],"level":n["level"],"line":n["lineRange"][0]}),
            "definitions"=>json!({"name":n["name"],"kind":n["kind"],"fields":array(n,"fields"),"startLine":n["lineRange"][0],"endLine":n["lineRange"][1]}),
            "services"=>{let mut v=json!({"name":n["name"],"image":n["image"],"ports":array(n,"ports")});if !array(n,"lineRange").is_empty(){v["startLine"]=n["lineRange"][0].clone();v["endLine"]=n["lineRange"][1].clone();}v},
            "endpoints"=>json!({"method":n["method"],"path":n["path"],"startLine":n["lineRange"][0],"endLine":n["lineRange"][1]}),
            "resources"=>json!({"name":n["name"],"kind":n["kind"],"startLine":n["lineRange"][0],"endLine":n["lineRange"][1]}),
            _=>json!({"name":n["name"],"startLine":n["lineRange"][0],"endLine":n["lineRange"][1]})
        }).collect();
        if !values.is_empty() {
            base[key] = json!(values);
        }
    }
    if let Some(c) = calls.filter(|c| !c.is_empty()) {
        base["callGraph"] = json!(c);
    }
    let path = file["path"].as_str().unwrap_or("");
    let incoming = array(imports, path);
    if !incoming.is_empty() {
        base["metrics"]["importCount"] = json!(incoming.len());
    } else if a["imports"].is_array() {
        base["metrics"]["importCount"] = json!(
            array(a, "imports")
                .iter()
                .filter(|i| i["source"].as_str().unwrap_or("").starts_with('.'))
                .count()
        );
    }
    for (key, count) in [
        ("exports", "exportCount"),
        ("functions", "functionCount"),
        ("classes", "classCount"),
        ("sections", "sectionCount"),
        ("definitions", "definitionCount"),
        ("services", "serviceCount"),
        ("endpoints", "endpointCount"),
        ("steps", "stepCount"),
        ("resources", "resourceCount"),
    ] {
        if a[key].is_array() {
            base["metrics"][count] = json!(array(a, key).len());
        }
    }
    base
}
pub fn extract_structure(input: &Value) -> Result<Value> {
    let root = input["projectRoot"]
        .as_str()
        .filter(|r| !r.is_empty())
        .ok_or_else(|| {
            Error::Invalid("Invalid input: must contain projectRoot and batchFiles array".into())
        })?;
    let files = input["batchFiles"].as_array().ok_or_else(|| {
        Error::Invalid("Invalid input: must contain projectRoot and batchFiles array".into())
    })?;
    let mut results = vec![];
    let mut skipped = vec![];
    let mut unreadable = vec![];
    for f in files {
        let path = f["path"]
            .as_str()
            .ok_or_else(|| Error::Invalid("batch file path must be a string".into()))?;
        let content = match fs::read_to_string(Path::new(root).join(path)) {
            Ok(s) => s,
            Err(error) => {
                let code = match error.kind() {
                    std::io::ErrorKind::NotFound => "ENOENT",
                    std::io::ErrorKind::PermissionDenied => "EACCES",
                    std::io::ErrorKind::IsADirectory => "EISDIR",
                    std::io::ErrorKind::InvalidData => "EILSEQ",
                    _ => "IO_ERROR",
                };
                unreadable.push(json!({"path": path, "code": code}));
                skipped.push(path);
                continue;
            }
        };
        let content = content.replace("\r\n", "\n").replace('\r', "\n");
        let (total, nonempty) = count_lines(&content);
        let (analysis, calls) = if ["code", "script"].contains(&f["fileCategory"].as_str().unwrap_or("")) {
            analyze_file_full(path, &content)
        } else {
            (analyze_file(path, &content), None)
        };
        results.push(build_result(
            f,
            total,
            nonempty,
            analysis.as_ref(),
            calls.as_deref(),
            &input["batchImportData"],
        ));
    }
    Ok(
        json!({"scriptCompleted":true,"filesAnalyzed":results.len(),"filesSkipped":skipped,"filesUnreadable":unreadable,"results":results}),
    )
}
/// Import-map extraction intentionally has different traversal and alias rules
/// from the structural extractor. Keep this boundary separate.
pub fn extract_import_sources(language: &str, content: &str) -> Vec<Value> {
    try_extract_import_sources(language, content).unwrap_or_default()
}

/// Import refresh callers must distinguish parser failures from an empty import list.
pub fn try_extract_import_sources(language: &str, content: &str) -> Result<Vec<Value>> {
    let tree = parsers::parse(language, content)?;
    let root = N {
        raw: tree.root_node(),
        source: content,
    };
    let mut a = empty();
    fn descendants<'a>(n: &N<'a>, ty: &str) -> Vec<N<'a>> {
        let mut out = vec![];
        for c in n.children() {
            if c.ty() == ty {
                out.push(c.clone());
            }
            out.extend(descendants(&c, ty));
        }
        out
    }
    match language {
        "typescript" | "javascript" | "tsx" => {
            for n in root.children() {
                if ["import_statement", "export_statement"].contains(&n.ty().as_str())
                    && let Some(s) = n.child("string")
                {
                    import(
                        &mut a,
                        s.child("string_fragment")
                            .map(|n| n.text())
                            .unwrap_or_else(|| unquote(s.text())),
                        vec![],
                        n.row(),
                    );
                }
            }
        }
        "python" => {
            for n in root.children() {
                match n.ty().as_str() {
                    "import_statement" => {
                        // The reference checks `dn.parent is node`; tree_sitter creates a
                        // fresh parent wrapper, so unaliased imports are omitted there.
                        for ali in descendants(&n, "aliased_import") {
                            if let Some(d) = ali.child("dotted_name") {
                                import(
                                    &mut a,
                                    d.text(),
                                    vec![
                                        ali.child("identifier")
                                            .map(|n| n.text())
                                            .unwrap_or(d.text())
                                            .into(),
                                    ],
                                    n.row(),
                                );
                            }
                        }
                    }
                    "import_from_statement" => {
                        let module = n.field("module_name");
                        let mut spec = vec![];
                        for d in descendants(&n, "dotted_name") {
                            if module.as_ref().is_none_or(|m| {
                                !(m.raw.start_byte() <= d.raw.start_byte()
                                    && m.raw.end_byte() >= d.raw.end_byte())
                            }) {
                                spec.push(d.text().into());
                            }
                        }
                        for ali in descendants(&n, "aliased_import") {
                            if let Some(id) = ali.child("identifier") {
                                spec.push(id.text().into());
                            }
                        }
                        if n.child("wildcard_import").is_some() {
                            spec.push("*".into());
                        }
                        import(
                            &mut a,
                            module.map(|n| n.text()).unwrap_or(""),
                            spec,
                            n.row(),
                        );
                    }
                    _ => {}
                }
            }
        }
        "go" => {
            go(&root, &mut a);
            for i in a["imports"].as_array_mut().unwrap() {
                i["specifiers"] = json!([i["source"]
                    .as_str()
                    .unwrap_or("")
                    .rsplit('/')
                    .next()
                    .unwrap_or("")]);
            }
        }
        "java" => java(&root, &mut a, false, false),
        "csharp" => {
            fn walk(n: &N, a: &mut Value) {
                for c in n.children() {
                    match c.ty().as_str() {
                        "using_directive" => {
                            let s = if c.child("=").is_some() {
                                c.child("qualified_name")
                            } else {
                                c.child("qualified_name").or_else(|| c.child("identifier"))
                            };
                            if let Some(s) = s {
                                import(
                                    a,
                                    s.text(),
                                    vec![s.text().rsplit('.').next().unwrap_or("").into()],
                                    c.row(),
                                );
                            }
                        }
                        "namespace_declaration" | "file_scoped_namespace_declaration" => {
                            walk(&c, a)
                        }
                        _ => {}
                    }
                }
            }
            walk(&root, &mut a);
        }
        "php" => {
            fn walk(n: &N, a: &mut Value) {
                for c in n.children() {
                    if c.ty() == "namespace_use_declaration" {
                        if let Some(g) = c.child("namespace_use_group") {
                            let prefix = c.child("namespace_name").map(|n| n.text()).unwrap_or("");
                            let spec: Vec<_> = descendants(&g, "namespace_use_clause")
                                .iter()
                                .map(|n| {
                                    php_use_name(n, prefix)
                                        .rsplit('\\')
                                        .next()
                                        .unwrap_or("")
                                        .to_owned()
                                })
                                .collect();
                            let source = if prefix.is_empty() {
                                spec.join(", ")
                            } else {
                                format!("{prefix}\\{{{}}}", spec.join(", "))
                            };
                            import(a, &source, spec, c.row());
                        } else {
                            for clause in descendants(&c, "namespace_use_clause") {
                                let source = php_use_name(&clause, "");
                                let spec = source.rsplit('\\').next().unwrap_or("").to_owned();
                                import(a, &source, vec![spec], c.row());
                            }
                        }
                    } else if c.ty() == "namespace_definition"
                        && let Some(b) = c.child("declaration_list")
                    {
                        walk(&b, a);
                    }
                }
            }
            walk(&root, &mut a);
        }
        "rust" => rust(&root, &mut a),
        "c" | "cpp" => {
            for c in descendants(&root, "preproc_include") {
                if let Some(p) = c.field("path") {
                    let source = match p.ty().as_str() {
                        "system_lib_string" => {
                            p.text().trim_start_matches('<').trim_end_matches('>')
                        }
                        "string_literal" => p
                            .child("string_content")
                            .map(|n| n.text())
                            .unwrap_or_else(|| unquote(p.text())),
                        _ => p.text(),
                    };
                    import(&mut a, source, vec![source.into()], c.row());
                }
            }
        }
        _ => {}
    }
    Ok(array(&a, "imports")
        .iter()
        .map(|i| json!({"source":i["source"],"specifiers":i["specifiers"]}))
        .collect())
}
