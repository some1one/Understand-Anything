//! Deterministic graph analysis using native ordered maps and petgraph.
use crate::{Result, array, strings, tables};
use petgraph::{
    algo::{connected_components, is_cyclic_directed},
    graph::DiGraph,
};
use serde_json::{Value, json};
use statrs::distribution::{ContinuousCDF, StudentsT};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn constant(key: &str) -> Vec<String> {
    strings(&tables()["constants"][key])
}
fn has(key: &str, value: &str) -> bool {
    constant(key).iter().any(|s| s == value)
}
fn ends(key: &str, value: &str) -> bool {
    constant(key).iter().any(|s| value.ends_with(s))
}
fn parts(path: &str) -> Vec<String> {
    path.replace('\\', "/")
        .split('/')
        .filter(|p| !p.is_empty() && *p != ".")
        .map(str::to_owned)
        .collect()
}
fn base(node: &Value) -> String {
    if !s(node, "name").is_empty() {
        return s(node, "name").to_owned();
    }
    s(node, "filePath")
        .rsplit('/')
        .next()
        .unwrap_or("")
        .to_owned()
}
fn round4(n: f64) -> f64 {
    (n * 10000.).round_ties_even() / 10000.
}
pub fn common_dir_prefix(paths: &[String]) -> Vec<String> {
    let mut dirs = paths.iter().map(|p| {
        let mut p = parts(p);
        p.pop();
        p
    });
    let Some(mut common) = dirs.next() else {
        return vec![];
    };
    for d in dirs {
        let len = common.iter().zip(d).take_while(|(a, b)| **a == *b).count();
        common.truncate(len);
    }
    common
}
pub fn group_by_directory(nodes: &[Value]) -> (BTreeMap<String, Vec<String>>, Vec<String>) {
    let prefix = common_dir_prefix(
        &nodes
            .iter()
            .map(|n| s(n, "filePath").into())
            .collect::<Vec<_>>(),
    );
    let flat = nodes
        .iter()
        .all(|n| parts(s(n, "filePath")).len() <= prefix.len() + 1);
    let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for n in nodes {
        let p = parts(s(n, "filePath"));
        let b = base(n).to_lowercase();
        let key = if flat {
            if b.contains(".test.") || b.contains(".spec.") || b.starts_with("test_") {
                "test".into()
            } else if b.contains(".config.") || b.ends_with(".config") {
                "config".into()
            } else {
                b.rsplit_once('.')
                    .map(|(_, ext)| ext.to_owned())
                    .unwrap_or_else(|| "root".into())
            }
        } else if p.len() > prefix.len() + 1 {
            p[prefix.len()].clone()
        } else {
            "root".into()
        };
        groups.entry(key).or_default().push(s(n, "id").into());
    }
    (groups, prefix)
}
pub fn classify_file(node: &Value) -> Option<String> {
    let path = s(node, "filePath").replace('\\', "/");
    let low = path.to_lowercase();
    let b = base(node);
    let blow = b.to_lowercase();
    let framed = format!("/{low}");
    if constant("TEST_FILE_REGEXES")
        .iter()
        .any(|p| regex::Regex::new(p).is_ok_and(|r| r.is_match(&b)))
    {
        return Some("test".into());
    }
    let label = if blow.ends_with(".d.ts") {
        "types"
    } else if has("ENTRY_FILENAMES", &b) {
        "entry"
    } else if b == "main.go" {
        return framed.contains("/cmd/").then(|| "entry".into());
    } else if has("CONFIG_FILENAMES", &b) {
        "config"
    } else if b == "Dockerfile"
        || blow.starts_with("dockerfile.")
        || blow.starts_with("docker-compose")
        || ends("INFRA_EXTENSIONS", &low)
    {
        "infrastructure"
    } else if framed.contains("/.github/workflows/")
        || has("CI_FILENAMES", &b)
        || constant("CI_DIR_SEGMENTS")
            .iter()
            .any(|s| framed.contains(&format!("/{s}/")))
    {
        "ci-cd"
    } else if low.ends_with(".sql") {
        "data"
    } else if ends("TYPE_DEF_EXTENSIONS", &low) {
        "types"
    } else if ends("DOC_EXTENSIONS", &low) {
        "documentation"
    } else if b == "Makefile" {
        "infrastructure"
    } else {
        return None;
    };
    Some(label.into())
}
pub fn deployment_topology(nodes: &[Value]) -> Value {
    let mut out = json!({"hasDockerfile":false,"hasCompose":false,"hasK8s":false,"hasTerraform":false,"hasCI":false});
    let mut infra = BTreeSet::new();
    for n in nodes {
        let path = s(n, "filePath").replace('\\', "/");
        let low = path.to_lowercase();
        let b = base(n);
        let blow = b.to_lowercase();
        let seg: BTreeSet<_> = low.split('/').collect();
        let key = if b == "Dockerfile" || blow.starts_with("dockerfile.") {
            Some("hasDockerfile")
        } else if blow.starts_with("docker-compose") {
            Some("hasCompose")
        } else if ends("INFRA_EXTENSIONS", &low) {
            Some("hasTerraform")
        } else if (seg.contains("workflows") && seg.contains(".github"))
            || has("CI_FILENAMES", &b)
            || constant("CI_DIR_SEGMENTS")
                .iter()
                .any(|s| seg.contains(s.as_str()))
        {
            Some("hasCI")
        } else if constant("INFRA_DIR_SEGMENTS")
            .iter()
            .any(|s| seg.contains(s.as_str()))
        {
            Some("hasK8s")
        } else {
            None
        };
        if let Some(key) = key {
            out[key] = json!(true);
            infra.insert(path);
        }
    }
    out["infraFiles"] = json!(infra);
    out
}
fn ranks(values: &[usize]) -> Vec<f64> {
    let mut indices: Vec<_> = (0..values.len()).collect();
    indices.sort_by_key(|i| values[*i]);
    let mut out = vec![0.; values.len()];
    let mut start = 0;
    while start < indices.len() {
        let mut end = start + 1;
        while end < indices.len() && values[indices[start]] == values[indices[end]] {
            end += 1;
        }
        let rank = (start + end + 1) as f64 / 2.;
        for i in &indices[start..end] {
            out[*i] = rank;
        }
        start = end;
    }
    out
}
pub fn graph_metrics(
    ids: &[String],
    edges: &[Value],
) -> (Value, BTreeMap<String, usize>, BTreeMap<String, usize>) {
    let mut graph = DiGraph::<String, ()>::new();
    let mut indices = BTreeMap::new();
    for id in ids {
        indices
            .entry(id.clone())
            .or_insert_with(|| graph.add_node(id.clone()));
    }
    let mut seen = BTreeSet::new();
    for e in edges {
        let (src, tgt) = (s(e, "source"), s(e, "target"));
        if src != tgt
            && indices.contains_key(src)
            && indices.contains_key(tgt)
            && seen.insert((src, tgt))
        {
            graph.add_edge(indices[src], indices[tgt], ());
        }
    }
    let mut fan_in = BTreeMap::new();
    let mut fan_out = BTreeMap::new();
    for (id, i) in &indices {
        fan_in.insert(
            id.clone(),
            graph.neighbors_directed(*i, petgraph::Incoming).count(),
        );
        fan_out.insert(
            id.clone(),
            graph.neighbors_directed(*i, petgraph::Outgoing).count(),
        );
    }
    let n = graph.node_count();
    let mut metrics = json!({"fileCount":n,"importEdgeCount":graph.edge_count(),"density":if n>1{round4(graph.edge_count()as f64/(n*(n-1))as f64)}else{0.},"weaklyConnectedComponents":connected_components(&graph),"isDag":!is_cyclic_directed(&graph)});
    if n >= 3 {
        let x = ranks(&fan_in.values().copied().collect::<Vec<_>>());
        let y = ranks(&fan_out.values().copied().collect::<Vec<_>>());
        let mean = (n + 1) as f64 / 2.;
        let varx = x.iter().map(|v| (v - mean).powi(2)).sum::<f64>();
        let vary = y.iter().map(|v| (v - mean).powi(2)).sum::<f64>();
        if varx > 0. && vary > 0. {
            let rho = (x
                .iter()
                .zip(&y)
                .map(|(x, y)| (x - mean) * (y - mean))
                .sum::<f64>()
                / (varx * vary).sqrt())
            .clamp(-1., 1.);
            let p = if rho.abs() == 1. {
                0.
            } else {
                let t = rho * ((n - 2) as f64 / ((rho + 1.) * (1. - rho))).sqrt();
                2. * StudentsT::new(0., 1., (n - 2) as f64).unwrap().sf(t.abs())
            };
            metrics["fanInFanOutSpearman"] = json!(round4(rho));
            metrics["fanInFanOutPValue"] = json!(round4(p));
        }
    }
    (metrics, fan_in, fan_out)
}
pub fn analyze(input: &Value) -> Result<Value> {
    crate::schemas::validate("input", input)?;
    let mut normalized = input.clone();
    if let Some(nodes) = normalized["fileNodes"].as_array_mut() {
        for node in nodes {
            if node.get("type").is_none() {
                node["type"] = json!("file");
            }
        }
    }
    for field in ["importEdges", "allEdges"] {
        if let Some(edges) = normalized[field].as_array_mut() {
            for edge in edges {
                if edge.get("type").is_none() {
                    edge["type"] = json!("imports");
                }
            }
        }
    }
    let input = &normalized;
    let nodes = array(input, "fileNodes");
    let import_edges = array(input, "importEdges");
    let (groups, prefix) = group_by_directory(nodes);
    let by_id: BTreeMap<_, _> = nodes.iter().map(|n| (s(n, "id"), n)).collect();
    let mut type_groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for n in nodes {
        type_groups
            .entry(s(n, "type").into())
            .or_default()
            .push(s(n, "id").into());
    }
    let node_group: BTreeMap<_, _> = groups
        .iter()
        .flat_map(|(g, ids)| ids.iter().map(move |id| (id.as_str(), g.as_str())))
        .collect();
    let ids = by_id.keys().map(|s| (*s).to_owned()).collect::<Vec<_>>();
    let (metrics, fan_in, fan_out) = graph_metrics(&ids, import_edges);
    let patterns: BTreeMap<String, String> = groups
        .keys()
        .filter_map(|g| {
            tables()["constants"]["DIRECTORY_PATTERN_MAP"][g.to_lowercase()]
                .as_str()
                .map(|label| (g.clone(), label.into()))
        })
        .collect();
    let file_patterns: BTreeMap<String, String> = nodes
        .iter()
        .filter_map(|n| classify_file(n).map(|label| (s(n, "id").into(), label)))
        .collect();
    let mut cross = BTreeMap::new();
    for e in array(input, "allEdges") {
        if let (Some(src), Some(tgt)) = (by_id.get(s(e, "source")), by_id.get(s(e, "target"))) {
            let (a, b) = (s(src, "type"), s(tgt, "type"));
            if a != b {
                *cross.entry((a, b, s(e, "type"))).or_insert(0usize) += 1;
            }
        }
    }
    let mut cross: Vec<_> = cross.into_iter().collect();
    cross.sort_by_key(|(key, count)| (std::cmp::Reverse(*count), *key));
    let cross: Vec<_> = cross
        .into_iter()
        .map(|((a, b, t), n)| json!({"fromType":a,"toType":b,"edgeType":t,"count":n}))
        .collect();
    let mut inter: BTreeMap<(String, String), usize> = BTreeMap::new();
    let mut internal: BTreeMap<String, usize> = BTreeMap::new();
    let mut total: BTreeMap<String, usize> = BTreeMap::new();
    for e in import_edges {
        let (gs, gt) = (
            node_group.get(s(e, "source")),
            node_group.get(s(e, "target")),
        );
        if let (Some(a), Some(b)) = (gs, gt)
            && a != b
        {
            *inter.entry(((*a).into(), (*b).into())).or_default() += 1;
        }
        if let Some(g) = gs.filter(|_| gs == gt) {
            *internal.entry(g.to_string()).or_default() += 1;
            *total.entry(g.to_string()).or_default() += 1;
        } else {
            for g in [gs, gt].into_iter().flatten() {
                *total.entry((*g).into()).or_default() += 1;
            }
        }
    }
    let mut ordered: Vec<_> = inter.iter().collect();
    ordered.sort_by_key(|(k, v)| (std::cmp::Reverse(**v), (*k).clone()));
    let inter_json: Vec<_> = ordered
        .iter()
        .map(|((a, b), n)| json!({"from":a,"to":b,"count":n}))
        .collect();
    let mut direction = vec![];
    let mut pairs = BTreeSet::new();
    for ((a, b), _) in &ordered {
        let mut pair = [a.as_str(), b.as_str()];
        pair.sort();
        if !pairs.insert(pair) {
            continue;
        }
        let ab = inter
            .get(&(a.to_string(), b.to_string()))
            .copied()
            .unwrap_or(0);
        let ba = inter
            .get(&(b.to_string(), a.to_string()))
            .copied()
            .unwrap_or(0);
        if ab > ba {
            direction.push(json!({"dependent":a,"dependsOn":b}));
        } else if ba > ab {
            direction.push(json!({"dependent":b,"dependsOn":a}));
        }
    }
    let density:BTreeMap<_,_>=groups.keys().map(|g|{let t=total.get(g).copied().unwrap_or(0);let i=internal.get(g).copied().unwrap_or(0);(g,json!({"internalEdges":i,"totalEdges":t,"density":if t>0{round4(i as f64/t as f64)}else{0.}}))}).collect();
    let from: BTreeSet<_> = inter.keys().map(|(a, _)| a).collect();
    let to: BTreeSet<_> = inter.keys().map(|(_, b)| b).collect();
    let matrix: BTreeMap<_, _> = from
        .into_iter()
        .map(|a| {
            (
                a,
                to.iter()
                    .map(|b| {
                        (
                            *b,
                            inter.get(&(a.clone(), (*b).clone())).copied().unwrap_or(0),
                        )
                    })
                    .collect::<BTreeMap<_, _>>(),
            )
        })
        .collect();
    let topology = deployment_topology(nodes);
    let mut schema = BTreeSet::new();
    let mut migration = BTreeSet::new();
    let mut models = BTreeSet::new();
    let mut api = BTreeSet::new();
    for n in nodes {
        let path = s(n, "filePath").replace('\\', "/");
        let low = path.to_lowercase();
        let seg: BTreeSet<_> = low.split('/').collect();
        let is_schema =
            ends("SCHEMA_EXTENSIONS", &low) || base(n).to_lowercase().starts_with("schema.");
        let is_migration = seg.contains("migrations");
        let pattern = node_group
            .get(s(n, "id"))
            .and_then(|g| patterns.get(*g))
            .map(String::as_str);
        if is_schema {
            schema.insert(path.clone());
        }
        if is_migration {
            migration.insert(path.clone());
        }
        if !is_schema && !is_migration && (seg.contains("models") || pattern == Some("data")) {
            models.insert(path.clone());
        }
        if pattern == Some("api") {
            api.insert(path);
        }
    }
    let pipeline = json!({"schemaFiles":schema,"migrationFiles":migration,"dataModelFiles":models,"apiHandlerFiles":api});
    let undocumented: Vec<_> = groups
        .iter()
        .filter(|(_, ids)| {
            !ids.iter().any(|id| {
                by_id[id.as_str()]["type"] == "document"
                    || ends("DOC_EXTENSIONS", &base(by_id[id.as_str()]).to_lowercase())
            })
        })
        .map(|(g, _)| g)
        .collect();
    let docs = json!({"groupsWithDocs":groups.len()-undocumented.len(),"totalGroups":groups.len(),"coverageRatio":if groups.is_empty(){0.}else{round4((groups.len()-undocumented.len())as f64/groups.len()as f64)},"undocumentedGroups":undocumented});
    let recommendations = recommendations(
        nodes,
        &groups,
        &type_groups,
        &patterns,
        &file_patterns,
        &inter,
        &direction,
        &topology,
        &pipeline,
    );
    let result = json!({"scriptCompleted":true,"directoryGroups":groups,"nodeTypeGroups":type_groups,"crossCategoryEdges":cross,"interGroupImports":inter_json,"intraGroupDensity":density,"patternMatches":patterns,"deploymentTopology":topology,"dataPipeline":pipeline,"docCoverage":docs,"dependencyDirection":direction,"fileStats":{"totalFileNodes":nodes.len(),"filesPerGroup":groups.iter().map(|(g,ids)|(g,ids.len())).collect::<BTreeMap<_,_>>(),"nodeTypeCounts":type_groups.iter().map(|(g,ids)|(g,ids.len())).collect::<BTreeMap<_,_>>()},"fileFanIn":fan_in,"fileFanOut":fan_out,"commonPathPrefix":prefix.join("/"),"filePatternMatches":file_patterns,"interGroupMatrix":matrix,"graphMetrics":metrics,"phase2Recommendations":recommendations});
    crate::schemas::validate("output", &result)?;
    Ok(result)
}
#[allow(clippy::too_many_arguments)]
fn recommendations(
    nodes: &[Value],
    groups: &BTreeMap<String, Vec<String>>,
    types: &BTreeMap<String, Vec<String>>,
    patterns: &BTreeMap<String, String>,
    file_patterns: &BTreeMap<String, String>,
    inter: &BTreeMap<(String, String), usize>,
    direction: &[Value],
    topology: &Value,
    pipeline: &Value,
) -> Value {
    let mut gin: BTreeMap<String, usize> = BTreeMap::new();
    let mut gout: BTreeMap<String, usize> = BTreeMap::new();
    for ((a, b), count) in inter {
        *gout.entry(a.clone()).or_default() += count;
        *gin.entry(b.clone()).or_default() += count;
    }
    let roles: BTreeMap<_, _> = groups
        .keys()
        .map(|g| {
            let i = gin.get(g).copied().unwrap_or(0);
            let o = gout.get(g).copied().unwrap_or(0);
            let role = if i == 0 && o == 0 {
                "isolated"
            } else if o == 0 {
                "foundational"
            } else if i == 0 {
                "top"
            } else if i >= o {
                "foundational-leaning"
            } else {
                "consumer"
            };
            (g, json!({"importedBy":i,"imports":o,"role":role}))
        })
        .collect();
    let suggested: BTreeMap<_, _> = patterns
        .iter()
        .map(|(g, label)| (g, format!("layer:{label}")))
        .collect();
    let mut incoming: BTreeMap<String, usize> = groups.keys().map(|g| (g.clone(), 0)).collect();
    let mut next: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for d in direction {
        *incoming.entry(s(d, "dependent").into()).or_default() += 1;
        next.entry(s(d, "dependsOn").into())
            .or_default()
            .push(s(d, "dependent").into());
    }
    let mut queue: VecDeque<_> = incoming
        .iter()
        .filter(|(_, c)| **c == 0)
        .map(|(g, _)| g.clone())
        .collect();
    let mut order = vec![];
    while let Some(g) = queue.pop_front() {
        for d in next.get(&g).into_iter().flatten() {
            let c = incoming.get_mut(d).unwrap();
            *c -= 1;
            if *c == 0 {
                queue.push_back(d.clone());
            }
        }
        order.push(g);
    }
    if order.len() != groups.len() {
        order = groups.keys().cloned().collect();
        order.sort_by_key(|g| {
            std::cmp::Reverse(
                gin.get(g).copied().unwrap_or(0) as i64 - gout.get(g).copied().unwrap_or(0) as i64,
            )
        });
    }
    let ids = |ts: &[&str]| -> Vec<String> {
        let mut v: Vec<_> = ts
            .iter()
            .flat_map(|t| types.get(*t).into_iter().flatten().cloned())
            .collect();
        v.sort();
        v
    };
    let infra = ids(&["service", "resource"]);
    let ci = ids(&["pipeline"]);
    let doc = ids(&["document"]);
    let data = ids(&["table", "schema", "endpoint"]);
    let config = ids(&["config"]);
    let non_pkg = config
        .iter()
        .filter(|id| {
            nodes
                .iter()
                .find(|n| s(n, "id") == id.as_str())
                .is_some_and(|n| base(n).to_lowercase() != "package.json")
        })
        .count();
    let has_iac = ["hasDockerfile", "hasCompose", "hasK8s", "hasTerraform"]
        .iter()
        .any(|k| topology[*k] == true);
    let has_ci = topology["hasCI"] == true;
    let has_schema = !array(pipeline, "schemaFiles").is_empty();
    let pybool = |v| if v { "True" } else { "False" };
    let suggestion = |id: &str, ids: &Vec<String>, recommended: bool, reason: String| json!({"layerId":id,"nodeIds":ids,"recommended":recommended,"reason":reason});
    let suggestions = vec![
        suggestion(
            "layer:infrastructure",
            &infra,
            !infra.is_empty() || has_iac,
            format!(
                "{} infra node(s); IaC files detected={}",
                infra.len(),
                pybool(has_iac)
            ),
        ),
        suggestion(
            "layer:ci-cd",
            &ci,
            !ci.is_empty() || has_ci,
            format!(
                "{} pipeline node(s); CI detected={}",
                ci.len(),
                pybool(has_ci)
            ),
        ),
        suggestion(
            "layer:documentation",
            &doc,
            doc.len() >= 3,
            format!("{} document node(s) (threshold 3)", doc.len()),
        ),
        suggestion(
            "layer:data",
            &data,
            !data.is_empty() || has_schema,
            format!(
                "{} data node(s); schema files detected={}",
                data.len(),
                pybool(has_schema)
            ),
        ),
        suggestion(
            "layer:config",
            &config,
            non_pkg >= 3,
            format!("{non_pkg} config node(s) beyond package.json (threshold 3)"),
        ),
    ];
    let node_group: BTreeMap<_, _> = groups
        .iter()
        .flat_map(|(g, ids)| ids.iter().map(move |id| (id, g)))
        .collect();
    let mut assignment = BTreeMap::new();
    for n in nodes {
        let id = s(n, "id");
        let typ = s(n, "type");
        let fp = file_patterns.get(id).map(String::as_str).unwrap_or("");
        let g = node_group
            .get(&id.to_owned())
            .map(|s| s.as_str())
            .unwrap_or("root");
        let derived = g
            .trim()
            .to_lowercase()
            .chars()
            .map(|c| if c.is_alphanumeric() { c } else { '-' })
            .collect::<String>()
            .split('-')
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join("-");
        let layer = tables()["constants"]["NODE_TYPE_LAYER"][typ]
            .as_str()
            .or_else(|| tables()["constants"]["FILE_PATTERN_LAYER_OVERRIDE"][fp].as_str())
            .map(str::to_owned)
            .or_else(|| suggested.get(&g.to_owned()).cloned())
            .unwrap_or_else(|| {
                format!(
                    "layer:{}",
                    if derived.is_empty() { "root" } else { &derived }
                )
            });
        assignment.insert(id, layer);
    }
    json!({"groupRoles":roles,"suggestedLayerByGroup":suggested,"topologicalOrder":order,"nonCodeLayerSuggestions":suggestions,"defaultLayerAssignment":assignment})
}
