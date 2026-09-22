//! Context and prompt builders. They perform no network or filesystem work.
use crate::{array, search::SearchEngine, strings};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
fn s<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
fn members(graph: &Value, ids: &BTreeSet<String>) -> Vec<Value> {
    array(graph, "nodes")
        .iter()
        .filter(|n| ids.contains(s(n, "id")))
        .cloned()
        .collect()
}
fn layers(graph: &Value, ids: &BTreeSet<String>) -> Vec<Value> {
    array(graph, "layers")
        .iter()
        .filter(|l| strings(&l["nodeIds"]).iter().any(|id| ids.contains(id)))
        .cloned()
        .collect()
}
fn lines(items: &[&str]) -> Vec<String> {
    items.iter().map(|s| (*s).into()).collect()
}
fn add(out: &mut Vec<String>, items: &[&str]) {
    out.extend(lines(items));
}
fn display_name<'a>(nodes: &'a [Value], id: &'a str) -> &'a str {
    nodes
        .iter()
        .find(|n| s(n, "id") == id)
        .map(|n| s(n, "name"))
        .unwrap_or(id)
}
pub fn build_chat_context(graph: &Value, query: &str, max_nodes: usize) -> Value {
    let matched: BTreeSet<_> = SearchEngine::new(array(graph, "nodes").to_vec())
        .search(query, &[], max_nodes)
        .into_iter()
        .map(|r| r.node_id)
        .collect();
    let mut expanded = matched.clone();
    for e in array(graph, "edges") {
        if matched.contains(s(e, "source")) {
            expanded.insert(s(e, "target").into());
        }
        if matched.contains(s(e, "target")) {
            expanded.insert(s(e, "source").into());
        }
    }
    let edges: Vec<_> = array(graph, "edges")
        .iter()
        .filter(|e| expanded.contains(s(e, "source")) && expanded.contains(s(e, "target")))
        .collect();
    json!({"projectName":graph["project"]["name"],"projectDescription":graph["project"]["description"],"languages":graph["project"]["languages"],"frameworks":graph["project"]["frameworks"],"relevantNodes":members(graph,&expanded),"relevantEdges":edges,"relevantLayers":layers(graph,&expanded),"query":query})
}
pub fn format_context_for_prompt(c: &Value) -> String {
    let mut out = vec![
        format!("# Project: {}", s(c, "projectName")),
        String::new(),
        s(c, "projectDescription").into(),
        String::new(),
        format!("**Languages:** {}", strings(&c["languages"]).join(", ")),
        format!("**Frameworks:** {}", strings(&c["frameworks"]).join(", ")),
        String::new(),
    ];
    if !array(c, "relevantLayers").is_empty() {
        add(&mut out, &["## Relevant Layers", ""]);
        for l in array(c, "relevantLayers") {
            out.push(format!("### {}", s(l, "name")));
            add(&mut out, &[s(l, "description"), ""]);
        }
    }
    if !array(c, "relevantNodes").is_empty() {
        add(&mut out, &["## Code Components", ""]);
        for n in array(c, "relevantNodes") {
            out.push(format!("### {} ({})", s(n, "name"), s(n, "type")));
            if !s(n, "filePath").is_empty() {
                out.push(format!("- **File:** {}", s(n, "filePath")));
            }
            out.push(format!("- **Complexity:** {}", s(n, "complexity")));
            out.push(format!("- **Summary:** {}", s(n, "summary")));
            if !strings(&n["tags"]).is_empty() {
                out.push(format!("- **Tags:** {}", strings(&n["tags"]).join(", ")));
            }
            if !s(n, "languageNotes").is_empty() {
                out.push(format!("- **Language Notes:** {}", s(n, "languageNotes")));
            }
            out.push(String::new());
        }
    }
    if !array(c, "relevantEdges").is_empty() {
        add(&mut out, &["## Relationships", ""]);
        for e in array(c, "relevantEdges") {
            let nodes = array(c, "relevantNodes");
            let mut text = format!(
                "- {} --[{}]--> {}",
                display_name(nodes, s(e, "source")),
                s(e, "type"),
                display_name(nodes, s(e, "target"))
            );
            if !s(e, "description").is_empty() {
                text.push_str(&format!(": {}", s(e, "description")));
            }
            out.push(text);
        }
        out.push(String::new());
    }
    out.join("\n")
}
pub fn build_chat_prompt(graph: &Value, query: &str) -> String {
    let c = format_context_for_prompt(&build_chat_context(graph, query, 15));
    [
        "You are a knowledgeable assistant that answers questions about a software codebase.",
        "Use the following knowledge graph context to inform your answer.",
        "Reference specific files, functions, classes, and relationships from the graph.",
        "If layers are present, explain which architectural layer(s) are relevant.",
        "Be concise but thorough — link concepts to actual code locations.",
        "",
        "---",
        "",
        &c,
        "---",
        "",
        &format!("**User question:** {query}"),
    ]
    .join("\n")
}
pub fn build_explain_context(graph: &Value, path: &str) -> Value {
    let nodes = array(graph, "nodes");
    let edges = array(graph, "edges");
    let mut target = None;
    if !path.contains("://")
        && let Some((file, name)) = path.rsplit_once(':')
        && !file.is_empty()
    {
        target = nodes
            .iter()
            .find(|n| s(n, "filePath") == file && s(n, "name") == name);
    }
    let target = target.or_else(|| nodes.iter().find(|n| s(n, "filePath") == path));
    let mut children = vec![];
    let mut connected = BTreeSet::new();
    let mut relevant = vec![];
    let mut layer = None;
    if let Some(t) = target {
        let id = s(t, "id");
        children = nodes
            .iter()
            .filter(|n| {
                edges.iter().any(|e| {
                    s(e, "source") == id
                        && s(e, "target") == s(n, "id")
                        && s(e, "type") == "contains"
                })
            })
            .cloned()
            .collect();
        let related: BTreeSet<String> = children
            .iter()
            .map(|n| s(n, "id").into())
            .chain([id.into()])
            .collect();
        for e in edges {
            let src = s(e, "source");
            let tgt = s(e, "target");
            if related.contains(src) || related.contains(tgt) {
                relevant.push(e);
                if !related.contains(src) {
                    connected.insert(src.into());
                }
                if !related.contains(tgt) {
                    connected.insert(tgt.into());
                }
            }
        }
        layer = array(graph, "layers")
            .iter()
            .find(|l| strings(&l["nodeIds"]).iter().any(|n| n == id));
    }
    json!({"projectName":graph["project"]["name"],"path":path,"targetNode":target,"childNodes":children,"connectedNodes":members(graph,&connected),"relevantEdges":relevant,"layer":layer})
}
pub fn format_explain_prompt(c: &Value) -> String {
    let n = &c["targetNode"];
    if n.is_null() {
        return [
            "# Component Not Found",
            "",
            &format!(
                "The path \"{}\" was not found in the knowledge graph for {}.",
                s(c, "path"),
                s(c, "projectName")
            ),
            "",
            "Possible reasons:",
            "- The file hasn't been analyzed yet — try running /understand first",
            "- The path may be different in the graph — check the exact file path",
            "- The file may have been deleted or renamed since the last analysis",
        ]
        .join("\n");
    }
    let mut out = vec![
        format!("# Deep Dive: {}", s(n, "name")),
        String::new(),
        format!(
            "**Type:** {} | **Complexity:** {}",
            s(n, "type"),
            s(n, "complexity")
        ),
    ];
    if !s(n, "filePath").is_empty() {
        out.push(format!("**File:** `{}`", s(n, "filePath")));
    }
    if let Some(range) = n["lineRange"].as_array().filter(|r| r.len() >= 2) {
        out.push(format!("**Lines:** {}-{}", range[0], range[1]));
    }
    add(
        &mut out,
        &["", &format!("**Summary:** {}", s(n, "summary")), ""],
    );
    if c["layer"].is_object() {
        add(
            &mut out,
            &[
                &format!("## Architectural Layer: {}", s(&c["layer"], "name")),
                s(&c["layer"], "description"),
                "",
            ],
        );
    }
    for (key, title) in [
        ("childNodes", "Internal Components"),
        ("connectedNodes", "Connected Components"),
    ] {
        if !array(c, key).is_empty() {
            out.push(format!("## {title}"));
            for node in array(c, key) {
                out.push(format!(
                    "- **{}** ({}): {}",
                    s(node, "name"),
                    s(node, "type"),
                    s(node, "summary")
                ));
            }
            out.push(String::new());
        }
    }
    if !array(c, "relevantEdges").is_empty() {
        let mut nodes = vec![n.clone()];
        nodes.extend_from_slice(array(c, "childNodes"));
        nodes.extend_from_slice(array(c, "connectedNodes"));
        out.push("## Relationships".into());
        for e in array(c, "relevantEdges") {
            if e["type"] == "contains" {
                continue;
            }
            let desc = if s(e, "description").is_empty() {
                String::new()
            } else {
                format!(" — {}", s(e, "description"))
            };
            out.push(format!(
                "- {} --[{}]--> {}{desc}",
                display_name(&nodes, s(e, "source")),
                s(e, "type"),
                display_name(&nodes, s(e, "target"))
            ));
        }
        out.push(String::new());
    }
    if !s(n, "languageNotes").is_empty() {
        add(&mut out, &["## Language Notes", s(n, "languageNotes"), ""]);
    }
    add(
        &mut out,
        &[
            "## Instructions",
            "Provide a thorough explanation of this component:",
            "1. What it does and why it exists in the project",
            "2. How data flows through it (inputs, processing, outputs)",
            "3. How it interacts with connected components",
            "4. Any patterns, idioms, or design decisions worth noting",
            "5. Potential gotchas or areas of complexity",
            "",
        ],
    );
    out.join("\n")
}
pub fn build_diff_context(graph: &Value, changed: &[String]) -> Value {
    let nodes = array(graph, "nodes");
    let edges = array(graph, "edges");
    let mut ids = BTreeSet::new();
    let mut unmapped = vec![];
    for path in changed {
        let mut mapped = false;
        for n in nodes {
            if s(n, "filePath") == path {
                ids.insert(s(n, "id").to_owned());
                mapped = true;
            }
        }
        if !mapped {
            unmapped.push(path);
        }
    }
    for e in edges {
        if e["type"] == "contains" && ids.contains(s(e, "source")) {
            ids.insert(s(e, "target").into());
        }
    }
    let mut affected = BTreeSet::new();
    let mut impacted = vec![];
    for e in edges {
        let src = s(e, "source");
        let tgt = s(e, "target");
        if ids.contains(src) || ids.contains(tgt) {
            impacted.push(e);
            if !ids.contains(src) {
                affected.insert(src.into());
            }
            if !ids.contains(tgt) {
                affected.insert(tgt.into());
            }
        }
    }
    let all = ids.union(&affected).cloned().collect();
    json!({"projectName":graph["project"]["name"],"changedFiles":changed,"changedNodes":members(graph,&ids),"affectedNodes":members(graph,&affected),"impactedEdges":impacted,"affectedLayers":layers(graph,&all),"unmappedFiles":unmapped})
}
pub fn format_diff_analysis(c: &Value) -> String {
    let mut out = vec![
        format!("# Diff Analysis: {}", s(c, "projectName")),
        String::new(),
        "## Changed Components".into(),
        String::new(),
    ];
    if array(c, "changedNodes").is_empty() {
        out.push("No mapped components found for changed files.".into());
    } else {
        for n in array(c, "changedNodes") {
            out.push(format!(
                "- **{}** ({}) — {}",
                s(n, "name"),
                s(n, "type"),
                s(n, "summary")
            ));
            if !s(n, "filePath").is_empty() {
                out.push(format!("  - File: `{}`", s(n, "filePath")));
            }
            out.push(format!("  - Complexity: {}", s(n, "complexity")));
        }
    }
    add(&mut out, &["", "## Affected Components", ""]);
    if array(c, "affectedNodes").is_empty() {
        out.push("No downstream impact detected.".into());
    } else {
        add(
            &mut out,
            &[
                "These components are connected to changed code and may need attention:",
                "",
            ],
        );
        for n in array(c, "affectedNodes") {
            out.push(format!(
                "- **{}** ({}) — {}",
                s(n, "name"),
                s(n, "type"),
                s(n, "summary")
            ));
        }
    }
    add(&mut out, &["", "## Affected Layers", ""]);
    if array(c, "affectedLayers").is_empty() {
        out.push("No layers affected.".into());
    } else {
        for l in array(c, "affectedLayers") {
            out.push(format!("- **{}**: {}", s(l, "name"), s(l, "description")));
        }
    }
    out.push(String::new());
    if !array(c, "impactedEdges").is_empty() {
        add(&mut out, &["## Impacted Relationships", ""]);
        for e in array(c, "impactedEdges") {
            out.push(format!(
                "- {} --[{}]--> {}",
                s(e, "source"),
                s(e, "type"),
                s(e, "target")
            ));
        }
        out.push(String::new());
    }
    let unmapped = strings(&c["unmappedFiles"]);
    if !unmapped.is_empty() {
        add(
            &mut out,
            &[
                "## Unmapped Files",
                "",
                "These changed files are not yet in the knowledge graph:",
                "",
            ],
        );
        out.extend(unmapped.iter().map(|p| format!("- `{p}`")));
        out.push(String::new());
    }
    add(&mut out, &["## Risk Assessment", ""]);
    let complex: Vec<_> = array(c, "changedNodes")
        .iter()
        .filter(|n| n["complexity"] == "complex")
        .collect();
    let count = array(c, "affectedLayers")
        .iter()
        .map(|l| s(l, "id"))
        .collect::<BTreeSet<_>>()
        .len();
    let affected = array(c, "affectedNodes").len();
    if !complex.is_empty() {
        out.push(format!(
            "- **High complexity**: {} complex component(s) changed: {}",
            complex.len(),
            complex
                .iter()
                .map(|n| s(n, "name"))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if count > 1 {
        out.push(format!(
            "- **Cross-layer impact**: Changes span {count} architectural layers"
        ));
    }
    if affected > 5 {
        out.push(format!(
            "- **Wide blast radius**: {affected} components affected downstream"
        ));
    }
    if !unmapped.is_empty() {
        out.push(format!(
            "- **New/unmapped files**: {} files not in the knowledge graph (may need re-analysis)",
            unmapped.len()
        ));
    }
    if complex.is_empty() && count <= 1 && affected <= 5 && unmapped.is_empty() {
        out.push("- **Low risk**: Changes are localized with limited downstream impact.".into());
    }
    out.push(String::new());
    out.join("\n")
}
pub fn build_onboarding_guide(graph: &Value) -> String {
    let p = &graph["project"];
    let nodes = array(graph, "nodes");
    let edges = array(graph, "edges");
    let layers = array(graph, "layers");
    let mut out = vec![
        format!("# {}", s(p, "name")),
        String::new(),
        format!("> {}", s(p, "description")),
        String::new(),
        "| | |".into(),
        "|---|---|".into(),
        format!(
            "| **Languages** | {} |",
            strings(&p["languages"]).join(", ")
        ),
        format!(
            "| **Frameworks** | {} |",
            strings(&p["frameworks"]).join(", ")
        ),
        format!(
            "| **Components** | {} nodes, {} relationships |",
            nodes.len(),
            edges.len()
        ),
        format!("| **Last Analyzed** | {} |", s(p, "analyzedAt")),
        String::new(),
    ];
    if !layers.is_empty() {
        add(
            &mut out,
            &[
                "## Architecture",
                "",
                "The project is organized into the following layers:",
                "",
            ],
        );
        for l in layers {
            add(
                &mut out,
                &[
                    &format!("### {}", s(l, "name")),
                    "",
                    s(l, "description"),
                    "",
                ],
            );
            let names: Vec<_> = strings(&l["nodeIds"])
                .iter()
                .filter_map(|id| {
                    nodes
                        .iter()
                        .find(|n| s(n, "id") == id)
                        .map(|n| s(n, "name").to_owned())
                        .filter(|s| !s.is_empty())
                })
                .collect();
            if !names.is_empty() {
                add(
                    &mut out,
                    &[&format!("Key components: {}", names.join(", ")), ""],
                );
            }
        }
    }
    let concepts: Vec<_> = nodes.iter().filter(|n| n["type"] == "concept").collect();
    if !concepts.is_empty() {
        add(
            &mut out,
            &[
                "## Key Concepts",
                "",
                "Important architectural and domain concepts to understand:",
                "",
            ],
        );
        for n in concepts {
            add(
                &mut out,
                &[&format!("### {}", s(n, "name")), "", s(n, "summary"), ""],
            );
        }
    }
    let mut fan: BTreeMap<String, usize> = BTreeMap::new();
    for e in edges {
        if ["imports", "depends_on"].contains(&s(e, "type")) {
            let id = if e["direction"] == "backward" {
                s(e, "source")
            } else {
                s(e, "target")
            };
            *fan.entry(id.into()).or_default() += 1;
        }
    }
    let files: Vec<_> = nodes
        .iter()
        .filter(|n| n["type"] == "file" && !s(n, "filePath").is_empty())
        .collect();
    let mut foundations: Vec<_> = files
        .iter()
        .copied()
        .filter(|n| fan.get(s(n, "id")).copied().unwrap_or(0) > 0)
        .collect();
    foundations.sort_by_key(|n| (std::cmp::Reverse(fan[s(n, "id")]), s(n, "filePath")));
    foundations.truncate(8);
    if !foundations.is_empty() || !layers.is_empty() {
        add(&mut out, &["## Getting Started", ""]);
        if !foundations.is_empty() {
            add(
                &mut out,
                &[
                    "Start with the most depended-on files — these are the foundations the rest of the code builds on:",
                    "",
                ],
            );
            for n in foundations {
                let count = fan[s(n, "id")];
                out.push(format!(
                    "- `{}` — {} _(referenced by {count} component{})_",
                    s(n, "filePath"),
                    s(n, "summary"),
                    if count == 1 { "" } else { "s" }
                ));
            }
            out.push(String::new());
        }
        if !layers.is_empty() {
            add(
                &mut out,
                &[
                    "Then explore the codebase layer by layer, in the order listed under **Architecture** above.",
                    "",
                ],
            );
        }
    }
    if !files.is_empty() {
        add(
            &mut out,
            &[
                "## File Map",
                "",
                "| File | Purpose | Complexity |",
                "|------|---------|------------|",
            ],
        );
        for n in files {
            out.push(format!(
                "| `{}` | {} | {} |",
                s(n, "filePath"),
                s(n, "summary"),
                s(n, "complexity")
            ));
        }
        out.push(String::new());
    }
    let complex: Vec<_> = nodes
        .iter()
        .filter(|n| n["complexity"] == "complex")
        .collect();
    if !complex.is_empty() {
        add(
            &mut out,
            &[
                "## Complexity Hotspots",
                "",
                "These components are the most complex and deserve extra attention:",
                "",
            ],
        );
        for n in complex {
            out.push(format!(
                "- **{}** ({}): {}",
                s(n, "name"),
                s(n, "type"),
                s(n, "summary")
            ));
        }
        out.push(String::new());
    }
    add(
        &mut out,
        &[
            "---",
            "",
            &format!("*Generated from knowledge graph v{}*", s(graph, "version")),
            "",
        ],
    );
    out.join("\n")
}
