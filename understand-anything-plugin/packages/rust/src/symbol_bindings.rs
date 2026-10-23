//! Lexical bindings indexed before runtime effects are interpreted.
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use tree_sitter_language_pack::Node;

pub(crate) type Key = (usize, usize, String);
pub(crate) fn key(n: &Node) -> Key {
    (n.start_byte(), n.end_byte(), n.kind())
}
fn text<'a>(n: &Node, source: &'a str) -> &'a str {
    source.get(n.start_byte()..n.end_byte()).unwrap_or("")
}
fn children(n: &Node) -> Vec<Node> {
    (0..n.child_count())
        .filter_map(|i| n.child(i as u32))
        .filter(Node::is_named)
        .collect()
}
fn unwrap(mut node: Node) -> Node {
    while node.kind() == "parenthesized_expression" && node.named_child_count() == 1 {
        node = node.named_child(0).unwrap();
    }
    node
}
#[derive(Clone)]
enum Target {
    Known(Value),
    Assignment {
        scope: usize,
        name: Option<String>,
        id: usize,
    },
    Indirect(Box<Target>),
}
#[derive(Clone)]
struct Region {
    target: Target,
    direct: Key,
}
fn identifier(n: &Node, source: &str) -> Option<String> {
    if [
        "identifier",
        "constant",
        "type_identifier",
        "shorthand_property_identifier_pattern",
    ]
    .contains(&n.kind().as_str())
        && crate::symbol_coverage::spelling(text(n, source))
    {
        Some(text(n, source).to_owned())
    } else {
        None
    }
}
fn targets(n: Option<Node>, source: &str) -> Vec<Option<String>> {
    let Some(n) = n else {
        return vec![];
    };
    if [
        "identifier",
        "constant",
        "shorthand_property_identifier_pattern",
    ]
    .contains(&n.kind().as_str())
    {
        return vec![identifier(&n, source)];
    }
    for field in ["pattern", "name", "left", "value"] {
        if let Some(child) = n.child_by_field_name(field) {
            return targets(Some(child), source);
        }
    }
    if [
        "formal_parameters",
        "parameters",
        "method_parameters",
        "object_pattern",
        "array_pattern",
        "pattern_list",
        "tuple_pattern",
        "list_pattern",
        "rest_pattern",
        "rest_parameter",
        "splat_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    ]
    .contains(&n.kind().as_str())
    {
        return children(&n)
            .into_iter()
            .flat_map(|n| targets(Some(n), source))
            .collect();
    }
    if n.kind() == "typed_parameter" {
        return targets(n.named_child(0), source);
    }
    vec![]
}
fn unknown() -> Value {
    json!({"kind":"unknown"})
}
#[derive(Default)]
struct Scope {
    parent: Option<usize>,
    kind: &'static str,
    bindings: BTreeMap<String, BTreeMap<Key, Value>>,
    opaque: bool,
}
pub(crate) struct Index {
    scopes: Vec<Scope>,
    facts: BTreeMap<Key, usize>,
    declarations: BTreeSet<Key>,
    expressions: BTreeMap<Key, Target>,
    internal_names: Vec<(usize, String, Node, Target)>,
    python: bool,
}
impl Index {
    pub(crate) fn build(root: &Node, source: &str, python: bool) -> Self {
        let mut result = Self {
            scopes: vec![Scope {
                kind: "root",
                ..Default::default()
            }],
            facts: BTreeMap::new(),
            declarations: BTreeSet::new(),
            expressions: BTreeMap::new(),
            internal_names: vec![],
            python,
        };
        let mut writes = vec![];
        result.scan(root, source, 0, "", true, None, &mut writes);
        // Writes are resolved after later/hoisted declarations have been indexed.
        for (node, scope) in writes {
            for name in targets(node.child_by_field_name("left"), source) {
                if let Some(name) = name {
                    let destination = result
                        .lookup(scope, &name)
                        .ok()
                        .flatten()
                        .map(|(i, _)| i)
                        .unwrap_or(0);
                    let target = node
                        .child_by_field_name("right")
                        .map(unwrap)
                        .filter(|n| n.kind() == "class")
                        .map(|n| result.expression_target(&n))
                        .unwrap_or_else(unknown);
                    result.bind(destination, Some(name), &node, target);
                } else {
                    let mut current = Some(scope);
                    while let Some(i) = current {
                        result.scopes[i].opaque = true;
                        current = result.scopes[i].parent;
                    }
                }
            }
        }
        for (scope, name, node, target) in std::mem::take(&mut result.internal_names) {
            let target = result.resolve(&target);
            result.bind(scope, Some(name), &node, target);
        }
        result
    }
    fn resolve(&self, target: &Target) -> Value {
        match target {
            Target::Known(value) => value.clone(),
            Target::Assignment {
                scope,
                name: Some(name),
                id,
            } => match self.lookup(*scope, name) {
                Err(_) => unknown(),
                Ok(found) => {
                    let destination = found.map(|(scope, _)| scope).unwrap_or(0);
                    match self.scopes[destination].kind {
                        "root" => json!({"kind":"class","name":name}),
                        "namespace" => unknown(),
                        _ => json!({"kind":"local","id":id}),
                    }
                }
            },
            Target::Assignment { .. } => unknown(),
            Target::Indirect(target) => {
                let target = self.resolve(target);
                if target["kind"] == "local" {
                    target
                } else {
                    unknown()
                }
            }
        }
    }
    pub(crate) fn expression_target(&self, node: &Node) -> Value {
        self.expressions
            .get(&key(node))
            .map(|target| self.resolve(target))
            .unwrap_or_else(unknown)
    }
    pub(crate) fn is_binding(&self, node: &Node) -> bool {
        self.declarations.contains(&key(node))
    }
    fn mark_targets(&mut self, node: Option<Node>) {
        let Some(node) = node else {
            return;
        };
        if [
            "identifier",
            "constant",
            "shorthand_property_identifier_pattern",
        ]
        .contains(&node.kind().as_str())
        {
            self.declarations.insert(key(&node));
            return;
        }
        for field in ["pattern", "name", "left", "value"] {
            if let Some(child) = node.child_by_field_name(field) {
                self.mark_targets(Some(child));
                return;
            }
        }
        if [
            "formal_parameters",
            "parameters",
            "object_pattern",
            "array_pattern",
            "pattern_list",
            "tuple_pattern",
            "list_pattern",
            "rest_pattern",
            "rest_parameter",
            "splat_parameter",
            "list_splat_pattern",
            "dictionary_splat_pattern",
        ]
        .contains(&node.kind().as_str())
        {
            for child in children(&node) {
                self.mark_targets(Some(child));
            }
        } else if node.kind() == "typed_parameter" {
            self.mark_targets(node.named_child(0));
        }
    }
    fn scope(&mut self, parent: usize, kind: &'static str) -> usize {
        self.scopes.push(Scope {
            parent: Some(parent),
            kind,
            ..Default::default()
        });
        self.scopes.len() - 1
    }
    fn bind(&mut self, scope: usize, name: Option<String>, node: &Node, target: Value) {
        if let Some(name) = name {
            self.scopes[scope]
                .bindings
                .entry(name)
                .or_default()
                .insert(key(node), target);
        } else {
            self.scopes[scope].opaque = true;
        }
    }
    fn lookup(
        &self,
        mut scope: usize,
        name: &str,
    ) -> Result<Option<(usize, &BTreeMap<Key, Value>)>, ()> {
        loop {
            let s = &self.scopes[scope];
            if s.opaque {
                return Err(());
            }
            if let Some(values) = s.bindings.get(name) {
                return Ok(Some((scope, values)));
            }
            let function = s.kind == "function";
            let Some(parent) = s.parent else {
                return Ok(None);
            };
            scope = parent;
            if self.python && function {
                while self.scopes[scope].kind == "class" {
                    let Some(parent) = self.scopes[scope].parent else {
                        return Ok(None);
                    };
                    scope = parent;
                }
            }
        }
    }
    pub(crate) fn unbound(&self, node: &Node, name: &str) -> bool {
        self.facts
            .get(&key(node))
            .is_some_and(|scope| matches!(self.lookup(*scope, name), Ok(None)))
    }
    pub(crate) fn reference(&self, node: &Node, source: &str) -> Value {
        let Some(name) = identifier(node, source) else {
            return unknown();
        };
        let Some(scope) = self.facts.get(&key(node)) else {
            return unknown();
        };
        let Ok(Some((_, values))) = self.lookup(*scope, &name) else {
            return unknown();
        };
        let Some(first) = values.values().next() else {
            return unknown();
        };
        if values.values().all(|v| v == first) {
            first.clone()
        } else {
            unknown()
        }
    }
    fn class_target(&self, scope: usize, name: Option<String>, node: &Node) -> Value {
        if self.scopes[scope].kind == "root" {
            name.map(|name| json!({"kind":"class","name":name}))
                .unwrap_or_else(unknown)
        } else if self.scopes[scope].kind == "namespace" {
            unknown()
        } else {
            json!({"kind":"local","id":node.start_byte()})
        }
    }
    fn scan(
        &mut self,
        node: &Node,
        source: &str,
        enclosing: usize,
        parent_kind: &str,
        root: bool,
        region: Option<Region>,
        writes: &mut Vec<(Node, usize)>,
    ) {
        let kind = node.kind();
        let mut scope = enclosing;
        let name = node.child_by_field_name("name");
        let class = !root
            && [
                "class",
                "class_declaration",
                "abstract_class_declaration",
                "class_definition",
            ]
            .contains(&kind.as_str());
        let function = [
            "function_declaration",
            "generator_function_declaration",
            "function_definition",
            "method_definition",
            "function_expression",
            "generator_function",
            "arrow_function",
            "lambda",
        ]
        .contains(&kind.as_str());
        if class {
            let declared_target = self.class_target(
                enclosing,
                name.as_ref().and_then(|n| identifier(n, source)),
                node,
            );
            let target = if kind == "class" && !self.python {
                match &region {
                    Some(region) if region.direct == key(node) => region.target.clone(),
                    Some(region) => Target::Indirect(Box::new(region.target.clone())),
                    None => Target::Known(json!({"kind":"local","id":node.start_byte()})),
                }
            } else {
                Target::Known(declared_target)
            };
            if kind == "class" && !self.python {
                self.expressions.insert(key(node), target.clone());
            }
            if kind != "class" {
                if let Some(name) = &name {
                    self.bind(
                        enclosing,
                        identifier(name, source),
                        node,
                        self.resolve(&target),
                    );
                }
            }
            scope = self.scope(enclosing, "class");
            if !self.python {
                if let Some(name) = &name {
                    if let Some(name) = identifier(name, source) {
                        self.bind(scope, Some(name.clone()), node, self.resolve(&target));
                        self.internal_names
                            .push((scope, name, node.clone(), target.clone()));
                    }
                }
            }
        } else if function {
            if [
                "function_declaration",
                "generator_function_declaration",
                "function_definition",
            ]
            .contains(&kind.as_str())
            {
                if let Some(name) = &name {
                    self.bind(enclosing, identifier(name, source), node, unknown());
                }
            }
            scope = self.scope(enclosing, "function");
            if ["function_expression", "generator_function"].contains(&kind.as_str()) {
                if let Some(name) = &name {
                    self.bind(scope, identifier(name, source), node, unknown());
                }
            }
            for name in targets(
                node.child_by_field_name("parameters")
                    .or_else(|| node.child_by_field_name("parameter")),
                source,
            ) {
                self.bind(scope, name, node, unknown());
            }
        } else if !self.python
            && [
                "statement_block",
                "class_static_block",
                "for_statement",
                "for_in_statement",
                "catch_clause",
                "switch_statement",
                "with_statement",
            ]
            .contains(&kind.as_str())
        {
            scope = self.scope(enclosing, "block");
        }
        if !self.python
            && [
                "internal_module",
                "module",
                "namespace_definition",
                "namespace_declaration",
            ]
            .contains(&kind.as_str())
            && !root
        {
            if let Some(name) = &name {
                self.bind(enclosing, identifier(name, source), node, unknown());
            }
            scope = self.scope(enclosing, "namespace");
        }
        if !self.python && kind == "enum_declaration" {
            if let Some(name) = &name {
                self.bind(scope, identifier(name, source), node, unknown());
            }
        }
        self.facts.insert(key(node), scope);
        if class || function || kind == "variable_declarator" {
            self.mark_targets(name.clone());
        }
        if function {
            self.mark_targets(
                node.child_by_field_name("parameters")
                    .or_else(|| node.child_by_field_name("parameter")),
            );
        }
        if [
            "assignment",
            "augmented_assignment",
            "assignment_expression",
            "augmented_assignment_expression",
            "for_statement",
            "for_in_statement",
        ]
        .contains(&kind.as_str())
        {
            self.mark_targets(node.child_by_field_name("left"));
        }

        if kind == "with_statement" && !self.python {
            self.scopes[scope].opaque = true;
        }
        if kind == "catch_clause" {
            for name in targets(node.child_by_field_name("parameter"), source) {
                self.bind(scope, name, node, unknown());
            }
        }
        let mut value_region: Option<(Key, Region)> = None;
        if kind == "variable_declarator" {
            let mut destination = scope;
            if parent_kind == "variable_declaration" {
                while self.scopes[destination].kind == "block" {
                    destination = self.scopes[destination].parent.unwrap();
                }
            }
            let binding_name = name.as_ref().and_then(|n| identifier(n, source));
            let target = self.class_target(destination, binding_name.clone(), node);
            let value = node.child_by_field_name("value");
            let direct = value.clone().map(unwrap);
            for binding in targets(name.clone(), source) {
                let value = if direct.as_ref().is_some_and(|n| n.kind() == "class")
                    && binding == binding_name
                {
                    target.clone()
                } else {
                    unknown()
                };
                self.bind(destination, binding, node, value);
            }
            if let (Some(value), Some(direct)) = (value, direct) {
                value_region = Some((
                    key(&value),
                    Region {
                        target: Target::Known(target),
                        direct: key(&direct),
                    },
                ));
            }
        } else if !self.python
            && ["assignment_expression", "augmented_assignment_expression"].contains(&kind.as_str())
        {
            writes.push((node.clone(), scope));
            if let Some(value) = node.child_by_field_name("right") {
                let target = Target::Assignment {
                    scope,
                    name: node
                        .child_by_field_name("left")
                        .as_ref()
                        .and_then(|n| identifier(n, source)),
                    id: node.start_byte(),
                };
                value_region = Some((
                    key(&value),
                    Region {
                        target,
                        direct: key(&unwrap(value)),
                    },
                ));
            }
        } else if self.python
            && ["assignment", "augmented_assignment", "named_expression"].contains(&kind.as_str())
        {
            for name in targets(
                node.child_by_field_name("left")
                    .or_else(|| node.child_by_field_name("name")),
                source,
            ) {
                self.bind(scope, name, node, unknown());
            }
        }
        if kind == "for_in_statement" || self.python && kind == "for_statement" {
            if !self.python && node.child_by_field_name("kind").is_none() {
                writes.push((node.clone(), scope));
            }
            let mut destination = scope;
            if !self.python
                && node
                    .child_by_field_name("kind")
                    .is_some_and(|n| text(&n, source) == "var")
            {
                while self.scopes[destination].kind == "block" {
                    destination = self.scopes[destination].parent.unwrap();
                }
            }
            if self.python || node.child_by_field_name("kind").is_some() {
                for name in targets(node.child_by_field_name("left"), source) {
                    self.bind(destination, name, node, unknown());
                }
            }
        }
        if self.python && ["global_statement", "nonlocal_statement"].contains(&kind.as_str()) {
            for child in children(node) {
                if child.kind() == "identifier" {
                    self.bind(scope, identifier(&child, source), node, unknown());
                    self.bind(0, identifier(&child, source), node, unknown());
                }
            }
        }
        if self.python && kind == "as_pattern" {
            if let Some(alias) = node.child_by_field_name("alias") {
                for child in children(&alias) {
                    if child.kind() == "identifier" {
                        self.bind(scope, identifier(&child, source), node, unknown());
                    }
                }
            }
        }
        if !self.python && kind == "import_specifier" {
            self.bind(
                scope,
                node.child_by_field_name("alias")
                    .or(name)
                    .as_ref()
                    .and_then(|n| identifier(n, source)),
                node,
                unknown(),
            );
        } else if !self.python
            && ["import_clause", "namespace_import", "import_require_clause"]
                .contains(&kind.as_str())
        {
            for child in children(node) {
                if child.kind() == "identifier" {
                    self.bind(scope, identifier(&child, source), node, unknown());
                }
            }
        } else if self.python
            && ["import_statement", "import_from_statement"].contains(&kind.as_str())
        {
            let module = node.child_by_field_name("module_name").map(|n| key(&n));
            for child in children(node)
                .into_iter()
                .filter(|n| Some(key(n)) != module)
            {
                if child.kind() == "wildcard_import" {
                    self.scopes[scope].opaque = true;
                }
                if ["identifier", "dotted_name", "aliased_import"].contains(&child.kind().as_str())
                {
                    let imported = child
                        .child_by_field_name("name")
                        .unwrap_or_else(|| child.clone());
                    let name = child
                        .child_by_field_name("alias")
                        .or_else(|| {
                            children(&imported)
                                .into_iter()
                                .find(|n| n.kind() == "identifier")
                        })
                        .unwrap_or(imported);
                    self.bind(scope, identifier(&name, source), node, unknown());
                }
            }
        }
        let fence = class
            || function
            || [
                "public_field_definition",
                "field_definition",
                "pair",
                "object",
                "return_statement",
                "expression_statement",
                "class_static_block",
            ]
            .contains(&kind.as_str());
        for child in children(node) {
            let child_region = if let Some((value, value_scope)) = &value_region {
                if *value == key(&child) {
                    Some(value_scope.clone())
                } else if fence {
                    None
                } else {
                    region.clone()
                }
            } else if fence {
                None
            } else {
                region.clone()
            };
            self.scan(&child, source, scope, &kind, false, child_region, writes);
        }
    }
}
