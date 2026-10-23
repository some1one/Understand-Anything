//! AST-derived declaration scopes for strict structural comparisons.
//! This inventory does not by itself prove declaration coverage or deletion.
use serde_json::{Value, json};
use tree_sitter_language_pack::Node;

const CLASSES: &[&str] = &[
    "class",
    "module",
    "class_declaration",
    "abstract_class_declaration",
    "class_definition",
    "class_specifier",
    "struct_specifier",
    "struct_declaration",
    "struct_item",
    "enum_item",
    "interface_declaration",
];
const FUNCTIONS: &[&str] = &[
    "method",
    "singleton_method",
    "method_definition",
    "function_definition",
    "function_declaration",
    "generator_function_declaration",
    "generator_function",
    "function_item",
    "method_declaration",
    "constructor_declaration",
    "arrow_function",
    "function_expression",
    "lambda",
];
#[derive(Clone)]
enum Scope {
    File,
    Class(String),
    Local(usize),
    Unknown,
}
impl Scope {
    fn json(&self) -> Value {
        match self {
            Self::File => json!({"kind":"file"}),
            Self::Class(name) => json!({"kind":"class","name":name}),
            Self::Local(id) => json!({"kind":"local","id":id}),
            Self::Unknown => json!({"kind":"unknown"}),
        }
    }
}
fn text<'a>(node: &Node, content: &'a str) -> &'a str {
    content
        .get(node.start_byte()..node.end_byte())
        .unwrap_or("")
}
fn identifier(node: Option<Node>, content: &str) -> Option<String> {
    let node = node?;
    if ![
        "identifier",
        "type_identifier",
        "property_identifier",
        "constant",
        "field_identifier",
    ]
    .contains(&node.kind().as_str())
    {
        return None;
    }
    let name = text(&node, content);
    if name.is_empty() || !crate::symbol_coverage::spelling(name) {
        None
    } else {
        Some(name.to_owned())
    }
}
fn record(node: &Node, name: Option<String>, scope: &Scope) -> Value {
    json!({"name":name,"scope":scope.json(),"lineRange":[node.start_position().row+1,node.end_position().row+1]})
}
struct Inventory<'a> {
    content: &'a str,
    ruby: bool,
    effects: Vec<Value>,
    javascript: bool,
    functions: Vec<Value>,
    classes: Vec<Value>,
    unresolved: Vec<Value>,
    gaps: Vec<Value>,
    next_scope: usize,
}
impl Inventory<'_> {
    fn local(&mut self) -> Scope {
        self.next_scope += 1;
        Scope::Local(self.next_scope)
    }
    fn visit(
        &mut self,
        node: Node,
        enclosing: Scope,
        binding: Option<String>,
        object_member: bool,
        receiver: Scope,
    ) {
        let kind = node.kind();
        if self.ruby {
            self.effects.extend(crate::symbol_effects::ruby(
                &node,
                self.content,
                &enclosing.json(),
                &receiver.json(),
            ));
        }
        let is_class = CLASSES.contains(&kind.as_str());
        let is_function = FUNCTIONS.contains(&kind.as_str());
        let declared = identifier(node.child_by_field_name("name"), self.content);
        if let Some(gap) = crate::symbol_coverage::gap(
            &node,
            &enclosing.json(),
            &receiver.json(),
            self.content,
            is_class || is_function,
        ) {
            self.gaps.push(gap);
        }
        let mut children_receiver = receiver;
        let mut children_scope = enclosing.clone();
        if is_class {
            let expression = self.javascript && kind == "class";
            let name = if expression { binding } else { declared };
            let declaration_scope = if expression && name.is_none() {
                self.local()
            } else {
                enclosing.clone()
            };
            let entry = record(&node, name.clone(), &declaration_scope);
            if name.is_some() {
                self.classes.push(entry);
            } else {
                self.unresolved.push(entry);
                self.gaps.push(crate::symbol_coverage::entry(
                    &node,
                    &declaration_scope.json(),
                    None,
                    Some("class"),
                    "Unresolved declaration name",
                ));
            }
            children_scope = match declaration_scope {
                Scope::File => name.map(Scope::Class).unwrap_or(Scope::Unknown),
                Scope::Local(id) => Scope::Local(id),
                // Nested declaring types need qualified identity evidence; never
                // promote a nested class into an unrelated top-level owner.
                Scope::Class(_) | Scope::Unknown => Scope::Unknown,
            };
            children_receiver = children_scope.clone();
        } else if is_function {
            let value_function = [
                "arrow_function",
                "function_expression",
                "generator_function",
                "lambda",
            ]
            .contains(&kind.as_str());
            let name = if value_function { binding } else { declared };
            let mut owner = if object_member {
                self.local()
            } else {
                enclosing.clone()
            };
            // Rust impls and Go receivers require language-specific owner evidence.
            // Singleton methods on arbitrary objects likewise cannot inherit scope.
            if kind == "method_declaration" && node.child_by_field_name("receiver").is_some() {
                owner = Scope::Unknown;
            }
            if kind == "singleton_method" {
                let receiver = node
                    .child_by_field_name("object")
                    .or_else(|| node.child_by_field_name("receiver"));
                if receiver
                    .as_ref()
                    .is_some_and(|r| text(r, self.content) != "self")
                {
                    owner = Scope::Unknown;
                }
            }
            if matches!(owner, Scope::Unknown) {
                self.gaps.push(crate::symbol_coverage::entry(
                    &node,
                    &owner.json(),
                    name.clone(),
                    Some("callable"),
                    "Unresolved declaring type",
                ));
            }
            let entry = record(&node, name.clone(), &owner);
            if name.is_some() {
                self.functions.push(entry);
            } else if !value_function {
                self.unresolved.push(entry);
                self.gaps.push(crate::symbol_coverage::entry(
                    &node,
                    &owner.json(),
                    None,
                    Some("callable"),
                    "Unresolved declaration name",
                ));
            }
            children_receiver = owner;
            children_scope = self.local();
        } else if [
            "namespace_definition",
            "namespace_declaration",
            "impl_item",
            "singleton_class",
        ]
        .contains(&kind.as_str())
        {
            children_scope = Scope::Unknown;
            children_receiver = Scope::Unknown;
        } else if self.javascript
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
            children_scope = self.local();
        }
        // A value bound directly to a variable has that public name. An internal
        // function/class-expression name is not the variable's external identity.
        let value = if kind == "variable_declarator" {
            node.child_by_field_name("value")
        } else if kind == "assignment" {
            node.child_by_field_name("right")
        } else {
            None
        };
        let value_name = if kind == "variable_declarator" {
            identifier(node.child_by_field_name("name"), self.content)
        } else if kind == "assignment" {
            identifier(node.child_by_field_name("left"), self.content)
        } else {
            None
        };
        for i in 0..node.child_count() {
            if let Some(child) = node.child(i as u32) {
                let direct_value = value.as_ref().is_some_and(|v| {
                    v.start_byte() == child.start_byte() && v.end_byte() == child.end_byte()
                });
                let child_binding = if direct_value {
                    value_name.clone()
                } else {
                    None
                };
                self.visit(
                    child,
                    children_scope.clone(),
                    child_binding,
                    self.javascript && kind == "object",
                    children_receiver.clone(),
                );
            }
        }
    }
}
/// Return declarations with positive lexical ownership. Unknown ownership stays
/// explicit, and local declarations are never treated as file-level replacements.
pub fn collect(root: Node, content: &str, language: &str, structure: &Value) -> Value {
    let mut inventory = Inventory {
        content,
        ruby: language == "ruby",
        effects: vec![],
        javascript: ["typescript", "javascript", "tsx"].contains(&language),
        functions: vec![],
        classes: vec![],
        unresolved: vec![],
        gaps: vec![],
        next_scope: 0,
    };
    // Python's root is named `module`, the same node kind Ruby uses for a
    // declaring module. The parse root always establishes file scope.
    for i in 0..root.child_count() {
        if let Some(child) = root.child(i as u32) {
            inventory.visit(child, Scope::File, None, false, Scope::File);
        }
    }
    for (key, kind) in [("functions", "callable"), ("classes", "class")] {
        let declarations = if key == "functions" {
            &inventory.functions
        } else {
            &inventory.classes
        };
        for declaration in declarations {
            let exact = crate::array(structure, key).iter().any(|item| {
                item["name"] == declaration["name"] && item["lineRange"] == declaration["lineRange"]
            });
            let method = key == "functions"
                && declaration["scope"]["kind"] == "class"
                && crate::array(structure, "classes").iter().any(|class| {
                    class["name"] == declaration["scope"]["name"]
                        && crate::array(class, "methods").contains(&declaration["name"])
                });
            if !exact && !method {
                let mut gap = declaration.clone();
                gap["kind"] = json!(kind);
                gap["reason"] = json!("Declaration is not covered by structural extraction");
                inventory.gaps.push(gap);
            }
        }
    }
    if ![
        "javascript",
        "typescript",
        "tsx",
        "python",
        "ruby",
        "go",
        "rust",
        "cpp",
    ]
    .contains(&language)
    {
        inventory.gaps.push(crate::symbol_coverage::entry(
            &root,
            &Scope::Unknown.json(),
            None,
            None,
            "Language has no verified declaration coverage profile",
        ));
    }
    json!({"functions":inventory.functions,"classes":inventory.classes,"unresolved":inventory.unresolved,"coverageGaps":inventory.gaps,"effects":inventory.effects})
}
