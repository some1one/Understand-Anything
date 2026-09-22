//! Deterministic line and regular-expression parsers from the Python baseline.
use regex::Regex;
use serde_json::{Value, json};
fn re(s: &str) -> Regex {
    Regex::new(s).expect("constant parser regex")
}
fn line(s: &str, offset: usize) -> usize {
    s.as_bytes()[..offset.min(s.len())]
        .iter()
        .filter(|b| **b == b'\n')
        .count()
        + 1
}
fn section(name: &str, level: usize, start: usize, end: usize) -> Value {
    json!({"name":name,"level":level,"lineRange":[start,end]})
}
fn definition(name: &str, kind: &str, start: usize, end: usize, fields: Vec<String>) -> Value {
    json!({"name":name,"kind":kind,"lineRange":[start,end],"fields":fields})
}
fn ranged(name: &str, start: usize, end: usize) -> Value {
    json!({"name":name,"lineRange":[start,end]})
}
fn close_brace(s: &str) -> usize {
    let mut depth = 0isize;
    for (i, c) in s.char_indices() {
        if c == '{' {
            depth += 1;
        } else if c == '}' {
            depth -= 1;
            if depth == 0 {
                return i;
            }
        }
    }
    s.len()
}
fn section_ends(sections: &mut [Value], total: usize) {
    for i in 0..sections.len() {
        let end = if i + 1 < sections.len() {
            sections[i + 1]["lineRange"][0].as_u64().unwrap() - 1
        } else {
            total as u64
        };
        sections[i]["lineRange"][1] = json!(end);
    }
}
pub fn empty_analysis() -> Value {
    json!({"functions":[],"classes":[],"imports":[],"exports":[]})
}
pub fn strip_jsonc_syntax(source: &str) -> String {
    let c: Vec<char> = source.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    while i < c.len() {
        match c[i] {
            '"' => {
                out.push(c[i]);
                i += 1;
                while i < c.len() {
                    let ch = c[i];
                    out.push(ch);
                    i += 1;
                    if ch == '\\' && i < c.len() {
                        out.push(c[i]);
                        i += 1;
                    } else if ch == '"' {
                        break;
                    }
                }
            }
            '/' => {
                if c.get(i + 1) == Some(&'/') {
                    i += 2;
                    while i < c.len() && c[i] != '\n' {
                        i += 1;
                    }
                } else if c.get(i + 1) == Some(&'*') {
                    i += 2;
                    while i + 1 < c.len() && !(c[i] == '*' && c[i + 1] == '/') {
                        i += 1;
                    }
                    i += 2;
                } else {
                    out.push(c[i]);
                    i += 1;
                }
            }
            _ => {
                out.push(c[i]);
                i += 1;
            }
        }
    }
    re(r",(\s*[}\]])").replace_all(&out, "$1").into_owned()
}
fn parse_python_json(source: &str) -> Result<Value, serde_json::Error> {
    // json.loads accepts these constants; only the object keys matter here.
    let source = strip_jsonc_syntax(source);
    let mut out = String::new();
    let mut quoted = false;
    let mut escaped = false;
    let mut i = 0;
    while i < source.len() {
        let tail = &source[i..];
        if !quoted
            && let Some(token) = ["-Infinity", "Infinity", "NaN"]
                .into_iter()
                .find(|t| tail.starts_with(t))
        {
            out.push_str("null");
            i += token.len();
            continue;
        }
        let c = tail.chars().next().unwrap();
        out.push(c);
        i += c.len_utf8();
        if escaped {
            escaped = false;
        } else if quoted && c == '\\' {
            escaped = true;
        } else if c == '"' {
            quoted = !quoted;
        }
    }
    serde_json::from_str(&out)
}
// PyYAML accepts duplicate mapping keys (the last value wins), unlike the
// default serde_yaml mapping visitor. Preserve this boundary explicitly.
struct Yaml(serde_yaml::Value);
impl<'de> serde::Deserialize<'de> for Yaml {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Yaml;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("YAML value")
            }
            fn visit_unit<E: serde::de::Error>(self) -> Result<Yaml, E> {
                Ok(Yaml(serde_yaml::Value::Null))
            }
            fn visit_none<E: serde::de::Error>(self) -> Result<Yaml, E> {
                self.visit_unit()
            }
            fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Yaml, E> {
                Ok(Yaml(v.into()))
            }
            fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Yaml, E> {
                Ok(Yaml(v.into()))
            }
            fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Yaml, E> {
                Ok(Yaml(v.into()))
            }
            fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Yaml, E> {
                Ok(Yaml(v.into()))
            }
            fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Yaml, E> {
                Ok(Yaml(v.into()))
            }
            fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Yaml, E> {
                Ok(Yaml(v.into()))
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(self, mut seq: A) -> Result<Yaml, A::Error> {
                let mut out = vec![];
                while let Some(v) = seq.next_element::<Yaml>()? {
                    out.push(v.0);
                }
                Ok(Yaml(serde_yaml::Value::Sequence(out)))
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(self, mut map: A) -> Result<Yaml, A::Error> {
                let mut out = serde_yaml::Mapping::new();
                while let Some((k, v)) = map.next_entry::<Yaml, Yaml>()? {
                    out.insert(k.0, v.0);
                }
                Ok(Yaml(serde_yaml::Value::Mapping(out)))
            }
        }
        d.deserialize_any(Visitor)
    }
}
fn yaml_boolean(s: &str) -> Option<bool> {
    match s {
        "yes" | "Yes" | "YES" | "true" | "True" | "TRUE" | "on" | "On" | "ON" => Some(true),
        "no" | "No" | "NO" | "false" | "False" | "FALSE" | "off" | "Off" | "OFF" => Some(false),
        _ => None,
    }
}
pub fn analyze(language: &str, source: &str) -> Option<Value> {
    let mut out = empty_analysis();
    let lines: Vec<_> = source.split('\n').collect();
    let mut sections = vec![];
    let mut definitions = vec![];
    let mut steps = vec![];
    let mut resources = vec![];
    let mut endpoints = vec![];
    match language {
        "markdown" => {
            let mut fence = None;
            let heading = re(r"^(#{1,6})\s+(.+)");
            let fr = re(r"^(```+|~~~+)");
            for (i, l) in lines.iter().enumerate() {
                if let Some(m) = fr.captures(l) {
                    let marker = m[1].chars().next().unwrap();
                    if fence == Some(marker) {
                        fence = None;
                    } else if fence.is_none() {
                        fence = Some(marker);
                    }
                    continue;
                }
                if fence.is_none()
                    && let Some(m) = heading.captures(l)
                {
                    sections.push(section(m[2].trim(), m[1].len(), i + 1, i + 1));
                }
            }
            section_ends(&mut sections, lines.len());
            out["sections"] = json!(sections);
        }
        "yaml" | "kubernetes" | "docker-compose" | "github-actions" => {
            match serde_yaml::from_str::<Yaml>(source).map(|y| y.0) {
                Ok(serde_yaml::Value::Mapping(doc)) => {
                    for raw_key in doc.keys() {
                        let key = match raw_key {
                            serde_yaml::Value::String(s) => {
                                if s == "<<" {
                                    continue;
                                }
                                let quoted = re(&format!(r#"^["']{}["']\s*:"#, regex::escape(s)))
                                    .is_match(source)
                                    || lines.iter().any(|l| {
                                        re(&format!(r#"^["']{}["']\s*:"#, regex::escape(s)))
                                            .is_match(l)
                                    });
                                if !quoted && let Some(b) = yaml_boolean(s) {
                                    if b { "True".into() } else { "False".into() }
                                } else {
                                    s.clone()
                                }
                            }
                            serde_yaml::Value::Bool(b) => {
                                if *b {
                                    "True".into()
                                } else {
                                    "False".into()
                                }
                            }
                            serde_yaml::Value::Null => "None".into(),
                            serde_yaml::Value::Number(n) => n.to_string(),
                            _ => continue,
                        };
                        let pat = re(&format!(r#"^["']?{}["']?\s*:"#, regex::escape(&key)));
                        if let Some(i) = lines.iter().position(|l| pat.is_match(l)) {
                            sections.push(section(&key, 1, i + 1, i + 1));
                        }
                    }
                    section_ends(&mut sections, lines.len());
                }
                Ok(serde_yaml::Value::Sequence(doc)) => {
                    for (i, v) in doc.iter().enumerate() {
                        let fallback = format!("[{i}]");
                        let name = ["name", "id", "kind"]
                            .iter()
                            .find_map(|f| {
                                v[*f].as_str().filter(|name| {
                                    yaml_boolean(name).is_none()
                                        || !re(&format!(
                                            r"(?m)^\s*(?:-\s+)?{}:\s*{}\s*$",
                                            regex::escape(f),
                                            regex::escape(name)
                                        ))
                                        .is_match(source)
                                })
                            })
                            .unwrap_or(&fallback);
                        sections.push(section(name, 1, 1, lines.len()));
                    }
                }
                Ok(_) => {}
                Err(_) => {
                    let pat = re(r"^(\w[\w-]*)\s*:");
                    for (i, l) in lines.iter().enumerate() {
                        if let Some(m) = pat.captures(l) {
                            sections.push(section(&m[1], 1, i + 1, i + 1));
                        }
                    }
                    section_ends(&mut sections, lines.len());
                }
            }
            out["sections"] = json!(sections);
        }
        "json" | "jsonc" | "json-schema" | "openapi" => {
            if let Ok(Value::Object(doc)) = parse_python_json(source) {
                for key in doc.keys() {
                    let escaped = crate::domain_context::ascii_json(&json!(key)).unwrap();
                    if let Some(i) = lines.iter().position(|l| l.contains(&escaped)) {
                        sections.push(section(key, 1, i + 1, i + 1));
                    }
                }
                section_ends(&mut sections, lines.len());
            }
            out["sections"] = json!(sections);
        }
        "toml" => {
            let pat = re(r"^\s*\[(\[?)([^\]]+)\]?\]");
            for (i, l) in lines.iter().enumerate() {
                if let Some(m) = pat.captures(l) {
                    let name = m[2].trim();
                    let display = if &m[1] == "[" {
                        format!("[[{name}]]")
                    } else {
                        name.into()
                    };
                    sections.push(section(&display, name.split('.').count(), i + 1, i + 1));
                }
            }
            section_ends(&mut sections, lines.len());
            out["sections"] = json!(sections);
        }
        "env" => {
            let pat = re(r"^([A-Za-z_][A-Za-z0-9_]*)=");
            for (i, l) in lines.iter().enumerate() {
                if let Some(m) = pat.captures(l.trim()) {
                    definitions.push(definition(&m[1], "variable", i + 1, i + 1, vec![]));
                }
            }
            out["definitions"] = json!(definitions);
        }
        "dockerfile" => {
            let from = re(r"(?i)^FROM\s+(\S+)(?:\s+AS\s+(\S+))?");
            let expose = re(r"(?i)^EXPOSE\s+(.+)");
            let step = re(
                r"(?i)^(FROM|RUN|COPY|ADD|WORKDIR|CMD|ENTRYPOINT|ENV|ARG|EXPOSE|VOLUME|USER|HEALTHCHECK)\s",
            );
            let starts: Vec<_> = lines
                .iter()
                .enumerate()
                .filter(|(_, l)| re(r"(?i)^FROM\s+").is_match(l))
                .map(|(i, _)| i)
                .collect();
            let mut services = vec![];
            for (s, start) in starts.iter().enumerate() {
                let end = starts.get(s + 1).copied().unwrap_or(lines.len()) - 1;
                if let Some(m) = from.captures(lines[*start]) {
                    let image = &m[1];
                    let name = m.get(2).map(|m| m.as_str()).unwrap_or_else(|| {
                        image
                            .split(':')
                            .next()
                            .unwrap_or(image)
                            .rsplit('/')
                            .next()
                            .unwrap_or(image)
                    });
                    let mut ports = vec![];
                    for l in &lines[*start..=end] {
                        if let Some(m) = expose.captures(l) {
                            ports.extend(
                                m[1].split_whitespace()
                                    .filter_map(|p| p.parse::<i64>().ok()),
                            );
                        }
                    }
                    services.push(json!({"name":name,"image":image,"ports":ports,"lineRange":[start+1,end+1]}));
                }
            }
            for (i, l) in lines.iter().enumerate() {
                if let Some(m) = step.captures(l) {
                    let name = format!(
                        "{} {}",
                        m[1].to_uppercase(),
                        l[m[1].len() + 1..]
                            .trim()
                            .chars()
                            .take(60)
                            .collect::<String>()
                    );
                    steps.push(ranged(&name, i + 1, i + 1));
                }
            }
            out["services"] = json!(services);
            out["steps"] = json!(steps);
        }
        "sql" => {
            for (kind, pat) in [
                (
                    "table",
                    r#"(?i)CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|")?(\w+)(?:`|")?"#,
                ),
                (
                    "view",
                    r#"(?i)CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:`|")?(\w+)(?:`|")?"#,
                ),
                (
                    "index",
                    r#"(?i)CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`|")?(\w+)(?:`|")?"#,
                ),
            ] {
                for m in re(pat).captures_iter(source) {
                    let start = m.get(0).unwrap().start();
                    let sl = line(source, start);
                    let mut end = sl;
                    let mut fields = vec![];
                    if kind == "table" {
                        let after = &source[start..];
                        end = after
                            .find(");")
                            .map(|p| line(source, start + p + 2))
                            .unwrap_or(sl + 5);
                        if let Some(open) = after.find('(')
                            && let Some(close) = after[open..].find(");")
                        {
                            for seg in after[open + 1..open + close].split(',') {
                                let seg = seg.trim();
                                if re(r"(?i)^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT|INDEX|KEY)")
                                    .is_match(seg)
                                {
                                    continue;
                                }
                                if let Some(m) = re(r#"^(?:`|")?(\w+)(?:`|")?\s+"#).captures(seg) {
                                    fields.push(m[1].into());
                                }
                            }
                        }
                    }
                    definitions.push(definition(&m[1], kind, sl, end, fields));
                }
            }
            out["definitions"] = json!(definitions);
        }
        "graphql" => {
            for m in
                re(r"(?m)^(type|input|enum|interface|union|scalar)\s+(\w+)").captures_iter(source)
            {
                if ["Query", "Mutation", "Subscription"].contains(&&m[2]) {
                    continue;
                }
                let start = m.get(0).unwrap().start();
                let after = &source[start..];
                let sl = line(source, start);
                let end = after
                    .find('}')
                    .map(|p| line(source, start + p + 1))
                    .unwrap_or(sl);
                let fields = if let Some(open) = after.find('{') {
                    let tail = &after[open..];
                    let end = close_brace(tail);
                    tail[1..end]
                        .split('\n')
                        .filter_map(|l| re(r"^(\w+)").captures(l.trim()).map(|m| m[1].to_owned()))
                        .collect()
                } else {
                    vec![]
                };
                definitions.push(definition(&m[2], &m[1], sl, end, fields));
            }
            for m in re(r"(?m)^type\s+(Query|Mutation|Subscription)\s*\{").captures_iter(source) {
                let mat = m.get(0).unwrap();
                let start = mat.end();
                let body_end = close_brace(&source[start - 1..]) + start - 1;
                let body = &source[start..body_end];
                for (j, l) in body.split('\n').enumerate() {
                    if let Some(w) = re(r"^(\w+)").captures(l.trim()) {
                        let ln = line(source, start) + j;
                        endpoints.push(json!({"method":m[1].to_owned(),"path":w[1].to_owned(),"lineRange":[ln,ln]}));
                    }
                }
            }
            out["definitions"] = json!(definitions);
            out["endpoints"] = json!(endpoints);
        }
        "protobuf" => {
            for kind in ["message", "enum", "service"] {
                let pat = re(&format!(r"(?m)^{kind}\s+(\w+)\s*\{{"));
                for m in pat.captures_iter(source) {
                    let mat = m.get(0).unwrap();
                    let start = mat.start();
                    let close = start + close_brace(&source[start..]);
                    let body = &source[mat.end()..close];
                    if kind == "service" {
                        for rpc in re(r"rpc\s+(\w+)\s*\(").captures_iter(body) {
                            let ln = line(source, mat.end() + rpc.get(0).unwrap().start());
                            endpoints.push(json!({"method":"rpc","path":format!("{}.{}",&m[1],&rpc[1]),"lineRange":[ln,ln]}));
                        }
                    } else {
                        let field = if kind == "message" {
                            r"(?m)^\s*(?:repeated\s+|optional\s+|required\s+|map<[^>]+>\s+)?\w+\s+(\w+)\s*="
                        } else {
                            r"(?m)^\s*(\w+)\s*="
                        };
                        let fields = re(field)
                            .captures_iter(body)
                            .map(|m| m[1].to_owned())
                            .collect();
                        definitions.push(definition(
                            &m[1],
                            kind,
                            line(source, start),
                            line(source, close + 1),
                            fields,
                        ));
                    }
                }
            }
            out["definitions"] = json!(definitions);
            out["endpoints"] = json!(endpoints);
        }
        "terraform" => {
            for kind in ["resource", "data", "module", "variable", "output"] {
                let pat = if ["resource", "data"].contains(&kind) {
                    format!(r#"(?m)^{kind}\s+"([^"]+)"\s+"([^"]+)"\s*\{{"#)
                } else {
                    format!(r#"(?m)^{kind}\s+"([^"]+)"\s*\{{"#)
                };
                for m in re(&pat).captures_iter(source) {
                    let start = m.get(0).unwrap().start();
                    let sl = line(source, start);
                    let end = line(source, start + close_brace(&source[start..]) + 1);
                    if ["variable", "output"].contains(&kind) {
                        definitions.push(definition(&m[1], kind, sl, end, vec![]));
                    } else {
                        let (name, typ) = match kind {
                            "resource" => (format!("{}.{}", &m[1], &m[2]), m[1].to_owned()),
                            "data" => (
                                format!("data.{}.{}", &m[1], &m[2]),
                                format!("data.{}", &m[1]),
                            ),
                            _ => (format!("module.{}", &m[1]), "module".into()),
                        };
                        resources.push(json!({"name":name,"kind":typ,"lineRange":[sl,end]}));
                    }
                }
            }
            out["resources"] = json!(resources);
            out["definitions"] = json!(definitions);
        }
        "makefile" => {
            let pat = re(r"^([a-zA-Z_.][a-zA-Z0-9_.-]*)(?:\s+.*)?:");
            for (i, l) in lines.iter().enumerate() {
                if l.contains(":=") || l.contains("?=") {
                    continue;
                }
                if let Some(m) = pat.captures(l) {
                    if m[1].starts_with('.') {
                        continue;
                    }
                    let mut end = i + 1;
                    while end < lines.len()
                        && (lines[end].is_empty()
                            || lines[end].starts_with('\t')
                            || lines[end].starts_with("  "))
                    {
                        end += 1;
                    }
                    steps.push(ranged(&m[1], i + 1, end));
                }
            }
            out["steps"] = json!(steps);
        }
        "shell" | "jenkinsfile" => {
            let pat = re(r"^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{?");
            let kw = re(r"^function\s+(\w+)\s*\{?");
            let mut functions = vec![];
            for (i, l) in lines.iter().enumerate() {
                if let Some(m) = pat.captures(l).or_else(|| kw.captures(l)) {
                    let next = (i + 1..lines.len()).find(|j| !lines[*j].trim().is_empty());
                    let start = if l.contains('{') {
                        i
                    } else if let Some(j) = next.filter(|j| lines[*j].trim().starts_with('{')) {
                        j
                    } else {
                        continue;
                    };
                    let mut depth = 0isize;
                    let mut end = start;
                    for (j, line) in lines.iter().enumerate().skip(start) {
                        depth += line.chars().filter(|c| *c == '{').count() as isize
                            - line.chars().filter(|c| *c == '}').count() as isize;
                        if depth == 0 {
                            end = j;
                            break;
                        }
                    }
                    functions
                        .push(json!({"name":m[1].to_owned(),"lineRange":[i+1,end+1],"params":[]}));
                }
            }
            out["functions"] = json!(functions);
        }
        _ => return None,
    }
    Some(out)
}
