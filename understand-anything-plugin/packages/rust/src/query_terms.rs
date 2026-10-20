//! Shared Unicode tokenization and dictionary-backed query filtering.
use crate::{Result, array, strings};
use regex::Regex;
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::OnceLock,
};
use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::UnicodeNormalization;
pub type Words = BTreeSet<String>;
pub type Lemmas = BTreeMap<String, BTreeMap<String, Vec<String>>>;
const STOP_WORDS: &str = "
a an the this that these those there here it its i me my mine we us our ours
he him his she her hers they them their theirs you your yours itself themselves
what which who whom whose where when why how whether whatever whichever
and or but if then than as of at by for from in into on onto to with about
across after before between during over through under until upon within
am is are was were be been being do does did doing have has had having
can could may might must shall should will would ought
please tell show explain describe find give get let know need want look
also just very really quite rather much many most more some any all each every
both either other another such same own only even ever still already again
";
const GENERIC_MODIFIERS: &str = "
good nice great simple basic minor major small large little big easy hard
quick slow pretty useful usual typical general particular specific
";
const TECHNICAL_MODIFIERS: &str = "
async asynchronous asynchronously sync synchronous synchronously concurrent
concurrently parallel sequential sequentially atomic atomically recursive
recursively public private protected static dynamic dynamically mutable immutable
optional required nullable null nonnull valid invalid secure insecure encrypted
unencrypted authenticated unauthenticated authorized unauthorized local remote
global internal external persistent transient readonly read-only write-only
thread-safe blocking nonblocking lazy eagerly lazily eager unique duplicate
idempotent deterministic non-deterministic bounded unbounded unsigned signed
true false not no never without
";

pub fn normalized(value: &str) -> String {
    value.nfkc().case_fold().collect()
}
fn regex(slot: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    slot.get_or_init(|| Regex::new(pattern).expect("constant regex"))
}
pub fn tokens(value: &str) -> Vec<String> {
    static WONT: OnceLock<Regex> = OnceLock::new();
    static CANT: OnceLock<Regex> = OnceLock::new();
    static NOT: OnceLock<Regex> = OnceLock::new();
    static SUFFIX: OnceLock<Regex> = OnceLock::new();
    static TOKEN: OnceLock<Regex> = OnceLock::new();
    let value: String = value.nfkc().collect::<String>().replace('’', "'");
    let value = regex(&WONT, r"(?i)\bwon't\b").replace_all(&value, "will not");
    let value = regex(&CANT, r"(?i)\bcan't\b").replace_all(&value, "can not");
    let value = regex(&NOT, r"(?i)n't\b").replace_all(&value, " not");
    let value = regex(&SUFFIX, r"(?i)'(?:s|re|ve|ll|d|m)\b").replace_all(&value, "");
    // Python's \w is Unicode alphanumeric plus underscore (not combining marks).
    regex(
        &TOKEN,
        r"[\p{L}\p{N}_]+(?:[./:\\-][\p{L}\p{N}_]+)*(?:\+\+|#)?",
    )
    .find_iter(&value)
    .map(|m| m.as_str().to_owned())
    .collect()
}
fn camel_boundary(chars: &[char], i: usize) -> bool {
    i > 0
        && chars[i].is_ascii_uppercase()
        && (chars[i - 1].is_ascii_lowercase()
            || chars[i - 1].is_ascii_digit()
            || (chars[i - 1].is_ascii_uppercase()
                && chars.get(i + 1).is_some_and(char::is_ascii_lowercase)))
}
pub fn parts(token: &str) -> Vec<String> {
    let chars: Vec<_> = token.chars().collect();
    let mut out = Vec::new();
    let mut part = String::new();
    for (i, &c) in chars.iter().enumerate() {
        if (camel_boundary(&chars, i) || !c.is_alphanumeric()) && !part.is_empty() {
            out.push(std::mem::take(&mut part));
        }
        if c.is_alphanumeric() {
            part.push(c);
        }
    }
    if !part.is_empty() {
        out.push(part);
    }
    out
}
fn uppercase(token: &str) -> bool {
    token.chars().any(char::is_uppercase) && !token.chars().any(char::is_lowercase)
}
fn technical(token: &str) -> bool {
    let chars: Vec<_> = token.chars().collect();
    token.contains(['_', '.', '/', ':', '\\', '-', '+', '#'])
        || (1..chars.len()).any(|i| camel_boundary(&chars, i))
        || (chars.len() > 1 && uppercase(token))
        || token.chars().any(|c| c.is_numeric())
}
fn contains(list: &str, word: &str) -> bool {
    list.split_whitespace().any(|w| w == word)
}
pub fn graph_vocabulary(graph: &Value) -> Words {
    let mut words = Words::new();
    for node in array(graph, "nodes") {
        for value in values(node, false) {
            for token in tokens(&value) {
                words.insert(normalized(&token));
                words.extend(parts(&token).iter().map(|p| normalized(p)));
            }
        }
    }
    words
}
fn values(node: &Value, summary: bool) -> Vec<String> {
    let mut values = ["id", "name", "filePath"]
        .iter()
        .filter_map(|k| node[k].as_str().map(str::to_owned))
        .collect::<Vec<_>>();
    if summary && let Some(s) = node["summary"].as_str() {
        values.push(s.to_owned());
    }
    values.extend(strings(&node["tags"]));
    values
}
pub struct Lexicon {
    lemmas: Lemmas,
}
impl Lexicon {
    pub fn load() -> Result<Self> {
        let lemmas = crate::dictionary_data::Sources::open()?.lemmas()?;
        Ok(Self { lemmas })
    }
    /// Preserve only entries whose removal changes the real filter. Test both
    /// original and normalized casing because dictionary protection is case-aware.
    pub fn needs_technical_protection(&self, word: &str) -> bool {
        let key = normalized(word);
        if !self.lemmas.contains_key(&key)
            && !contains(GENERIC_MODIFIERS, &key)
            && !contains(STOP_WORDS, &key)
        {
            return false;
        }
        [word.to_owned(), key.clone(), word.to_uppercase()]
            .iter()
            .any(|variant| {
                if normalized(variant) != key {
                    return false;
                }
                self.token_forms(variant, &normalized(variant), false, false, false)
                    != self.token_forms(
                        variant,
                        &normalized(variant),
                        false,
                        !contains(STOP_WORDS, &key) || (variant == word && technical(variant)),
                        false,
                    )
            })
    }
    fn token_forms(
        &self,
        token: &str,
        word: &str,
        protected: bool,
        cached: bool,
        graph: bool,
    ) -> Option<Words> {
        if protected || (graph && technical(token)) {
            return Some(Words::from([word.to_owned()]));
        }
        if graph || cached {
            return Some(self.forms(word));
        }
        if contains(STOP_WORDS, word) {
            return None;
        }
        if technical(token) && !(uppercase(token) && self.lemmas.contains_key(word)) {
            return Some(Words::from([word.to_owned()]));
        }
        let forms = self.forms(word);
        if !forms.iter().any(|w| contains(TECHNICAL_MODIFIERS, w)) {
            if forms.iter().any(|w| contains(GENERIC_MODIFIERS, w)) {
                return None;
            }
            if self.lemmas.get(word).is_some_and(|pos| {
                !pos.is_empty()
                    && pos
                        .keys()
                        .all(|p| ["ADJ", "ADV", "AUX"].contains(&p.as_str()))
            }) {
                return None;
            }
        }
        Some(forms)
    }
    pub fn forms(&self, word: &str) -> Words {
        let mut result = Words::from([word.to_owned()]);
        if let Some(entries) = self.lemmas.get(word) {
            result.extend(entries.values().flatten().map(|w| normalized(w)));
        }
        result
    }
    pub fn query_terms(&self, query: &str, graph: &Words, cached: &Words) -> Vec<Words> {
        static QUOTED: OnceLock<Regex> = OnceLock::new();
        let protected: Words = regex(&QUOTED, r#"`([^`]+)`|"([^"]+)""#)
            .captures_iter(query)
            .flat_map(|m| tokens(m.get(1).or_else(|| m.get(2)).unwrap().as_str()))
            .map(|t| normalized(&t))
            .collect();
        let cached_normalized: Words = cached.iter().map(|w| normalized(w)).collect();
        let mut result = Vec::new();
        for token in tokens(query) {
            let word = normalized(&token);
            let Some(forms) = self.token_forms(
                &token,
                &word,
                protected.contains(&word),
                (cached_normalized.contains(&word) && !contains(STOP_WORDS, &word))
                    || (cached.contains(&token) && technical(&token)),
                graph.contains(&word),
            ) else {
                continue;
            };
            if !result.contains(&forms) {
                result.push(forms);
            }
        }
        result
    }
    fn node_terms(&self, node: &Value) -> Words {
        let mut words = Words::new();
        for value in values(node, true) {
            for token in tokens(&value) {
                words.insert(normalized(&token));
                for part in parts(&token) {
                    words.extend(self.forms(&normalized(&part)));
                }
            }
        }
        words
    }
    pub fn matching_nodes<'a>(
        &self,
        graph: &'a Value,
        query: &str,
        cached: &Words,
    ) -> Vec<&'a Value> {
        let nodes: Vec<_> = array(graph, "nodes")
            .iter()
            .filter(|n| n.is_object())
            .collect();
        let terms = self.query_terms(query, &graph_vocabulary(graph), cached);
        let literal = normalized(
            query
                .trim()
                .trim_matches(['`', '"'])
                .trim_end_matches(['?', '!']),
        );
        let exact = |node: &&Value| {
            !literal.is_empty()
                && ["id", "name", "filePath"]
                    .iter()
                    .any(|k| normalized(node[k].as_str().unwrap_or("")) == literal)
        };
        if terms.is_empty() {
            return nodes.into_iter().filter(exact).collect();
        }
        let evidence: Vec<_> = nodes.iter().map(|n| self.node_terms(n)).collect();
        let matches: Vec<_> = nodes
            .iter()
            .zip(&evidence)
            .filter(|(n, words)| exact(n) || terms.iter().all(|t| !words.is_disjoint(t)))
            .map(|(n, _)| *n)
            .collect();
        if !matches.is_empty() {
            return matches;
        }
        nodes
            .into_iter()
            .zip(evidence)
            .filter(|(_, words)| terms.iter().any(|t| !words.is_disjoint(t)))
            .map(|(n, _)| n)
            .collect()
    }
}
