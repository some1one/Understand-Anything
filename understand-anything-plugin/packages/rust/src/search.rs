//! Lexical and semantic graph search. Scores are distances (zero is best).
use crate::{Error, Result, strings};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResult {
    pub node_id: String,
    pub score: f64,
}
fn ratio(a: &[char], b: &[char]) -> f64 {
    if a.is_empty() && b.is_empty() {
        return 1.;
    }
    let mut row = vec![0usize; b.len() + 1];
    for x in a {
        let mut previous = 0;
        for (j, y) in b.iter().enumerate() {
            let old = row[j + 1];
            row[j + 1] = if x == y {
                previous + 1
            } else {
                row[j + 1].max(row[j])
            };
            previous = old;
        }
    }
    2. * row[b.len()] as f64 / (a.len() + b.len()) as f64
}
pub fn partial_ratio(a: &str, b: &str) -> f64 {
    let a: Vec<_> = a.chars().collect();
    let b: Vec<_> = b.chars().collect();
    if a.is_empty() || b.is_empty() {
        return if a == b { 1. } else { 0. };
    }
    let (short, long) = if a.len() <= b.len() {
        (&a, &b)
    } else {
        (&b, &a)
    };
    let n = short.len();
    let mut best: f64 = 0.;
    for start in 0..long.len() {
        best = best.max(ratio(short, &long[start..long.len().min(start + n)]));
    }
    for end in 1..n {
        best = best.max(ratio(short, &long[..end]));
    }
    // RapidFuzz evaluates both orientations when lengths are equal.
    if a.len() == b.len() {
        for end in 1..n {
            best = best.max(ratio(&a[..end], &b)).max(ratio(&a[end..], &b));
        }
    }
    best
}
pub fn token_set_ratio(a: &str, b: &str) -> f64 {
    let a: BTreeSet<_> = a.split_whitespace().collect();
    let b: BTreeSet<_> = b.split_whitespace().collect();
    if a.is_empty() || b.is_empty() {
        return 0.;
    }
    let common = a.intersection(&b).copied().collect::<Vec<_>>().join(" ");
    let left = a.difference(&b).copied().collect::<Vec<_>>().join(" ");
    let right = b.difference(&a).copied().collect::<Vec<_>>().join(" ");
    if !common.is_empty() && (left.is_empty() || right.is_empty()) {
        return 1.;
    }
    let l = format!("{common} {left}").trim().to_owned();
    let r = format!("{common} {right}").trim().to_owned();
    let chars = |s: &str| s.chars().collect::<Vec<_>>();
    let mut score = ratio(&chars(&l), &chars(&r));
    if !common.is_empty() {
        score = score
            .max(ratio(&chars(&common), &chars(&l)))
            .max(ratio(&chars(&common), &chars(&r)));
    }
    score
}
#[derive(Debug, Clone)]
pub struct SearchEngine {
    nodes: Vec<Value>,
}
impl SearchEngine {
    pub fn new(nodes: Vec<Value>) -> Self {
        Self { nodes }
    }
    pub fn update_nodes(&mut self, nodes: Vec<Value>) {
        self.nodes = nodes;
    }
    pub fn search(&self, query: &str, types: &[String], limit: usize) -> Vec<SearchResult> {
        let tokens: Vec<_> = query.split_whitespace().map(str::to_lowercase).collect();
        if tokens.is_empty() {
            return vec![];
        }
        let mut results = vec![];
        for node in &self.nodes {
            if !types.is_empty() && !types.iter().any(|t| node["type"] == *t) {
                continue;
            }
            let mut best: f64 = 0.;
            for (field, weight) in [
                ("name", 0.4),
                ("tags", 0.3),
                ("summary", 0.2),
                ("languageNotes", 0.1),
            ] {
                let text = if node[field].is_array() {
                    strings(&node[field]).join(" ")
                } else {
                    node[field].as_str().unwrap_or("").to_owned()
                }
                .to_lowercase();
                if text.is_empty() {
                    continue;
                }
                let sim = tokens
                    .iter()
                    .map(|t| partial_ratio(t, &text).max(token_set_ratio(t, &text)))
                    .fold(0., f64::max)
                    + weight * 0.01;
                best = best.max(sim);
            }
            let score = 1. - best.min(1.);
            if score <= 0.4 {
                results.push(SearchResult {
                    node_id: node["id"].as_str().unwrap_or("").into(),
                    score,
                });
            }
        }
        results.sort_by(|a, b| a.score.total_cmp(&b.score));
        results.truncate(limit);
        results
    }
}
pub fn cosine_similarity(a: &[f64], b: &[f64]) -> Result<f64> {
    let ma = a.iter().map(|x| x * x).sum::<f64>().sqrt();
    cosine_with_query_magnitude(a, b, ma)
}
fn cosine_with_query_magnitude(a: &[f64], b: &[f64], ma: f64) -> Result<f64> {
    let mb = b.iter().map(|x| x * x).sum::<f64>().sqrt();
    if ma == 0. || mb == 0. {
        return Ok(0.);
    }
    if a.len() != b.len() {
        return Err(Error::Invalid("embedding vector dimensions differ".into()));
    }
    Ok(a.iter().zip(b).map(|(x, y)| x * y).sum::<f64>() / (ma * mb))
}
#[derive(Debug, Clone)]
pub struct SemanticSearchEngine {
    nodes: Vec<Value>,
    embeddings: BTreeMap<String, Vec<f64>>,
}
impl SemanticSearchEngine {
    pub fn new(nodes: Vec<Value>, embeddings: BTreeMap<String, Vec<f64>>) -> Self {
        Self { nodes, embeddings }
    }
    pub fn has_embeddings(&self) -> bool {
        !self.embeddings.is_empty()
    }
    pub fn add_embedding(&mut self, node_id: String, embedding: Vec<f64>) {
        self.embeddings.insert(node_id, embedding);
    }
    pub fn update_nodes(&mut self, nodes: Vec<Value>) {
        self.nodes = nodes;
    }
    pub fn search(
        &self,
        query: &[f64],
        limit: usize,
        threshold: f64,
        types: &[String],
    ) -> Result<Vec<SearchResult>> {
        let query_magnitude = query.iter().map(|x| x * x).sum::<f64>().sqrt();
        let mut results = vec![];
        for n in &self.nodes {
            if !types.is_empty() && !types.iter().any(|t| n["type"] == *t) {
                continue;
            }
            let id = n["id"].as_str().unwrap_or("");
            if let Some(e) = self.embeddings.get(id) {
                let sim = cosine_with_query_magnitude(query, e, query_magnitude)?;
                if sim >= threshold {
                    results.push(SearchResult {
                        node_id: id.into(),
                        score: 1. - sim,
                    });
                }
            }
        }
        results.sort_by(|a, b| a.score.total_cmp(&b.score));
        results.truncate(limit);
        Ok(results)
    }
}
