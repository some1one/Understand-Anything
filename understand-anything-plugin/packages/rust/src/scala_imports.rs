//! Filename-based Scala package imports, including package-object fallbacks.
use crate::imports::dir_of;
use std::collections::{BTreeMap, BTreeSet};
#[derive(Default)]
pub(crate) struct Index {
    files: BTreeMap<String, Vec<String>>,
    packages: BTreeMap<String, Vec<String>>,
}
impl Index {
    pub(crate) fn new(files: &BTreeSet<String>) -> Self {
        let mut index = Self::default();
        for path in files
            .iter()
            .filter(|p| p.ends_with(".scala") || p.ends_with(".sc"))
        {
            let parts: Vec<_> = path.split('/').collect();
            for i in 0..parts.len() {
                index
                    .files
                    .entry(parts[i..].join("/"))
                    .or_default()
                    .push(path.clone());
                if i + 1 < parts.len() {
                    index
                        .packages
                        .entry(parts[i..parts.len() - 1].join("/"))
                        .or_default()
                        .push(path.clone());
                }
            }
        }
        index
    }
    fn dotted(&self, name: &str) -> Vec<String> {
        let base = name.replace('.', "/");
        ["scala", "sc"]
            .iter()
            .flat_map(|ext| {
                self.files
                    .get(&format!("{base}.{ext}"))
                    .into_iter()
                    .flatten()
                    .cloned()
            })
            .collect()
    }
    pub(crate) fn resolve(&self, source: &str, specs: &[String]) -> Vec<String> {
        if specs.iter().any(|s| s == "*") {
            return self
                .packages
                .get(&source.trim_end_matches(".*").replace('.', "/"))
                .cloned()
                .unwrap_or_default();
        }
        let plain =
            specs.len() == 1 && !specs[0].is_empty() && source.ends_with(&format!(".{}", specs[0]));
        let mut out = BTreeSet::new();
        if plain {
            out.extend(self.dotted(source));
            if out.is_empty() {
                let package = &source[..source.len() - specs[0].len() - 1];
                out.extend(self.dotted(&format!("{package}.package")));
            }
        } else {
            let mut unresolved = false;
            for spec in specs.iter().filter(|s| !s.is_empty()) {
                let matches = self.dotted(&format!("{source}.{spec}"));
                unresolved |= matches.is_empty();
                out.extend(matches);
            }
            if unresolved {
                out.extend(self.dotted(&format!("{source}.package")));
            }
        }
        out.into_iter().collect()
    }
}
pub(crate) fn compare_members(a: &str, b: &str) -> std::cmp::Ordering {
    let package = |p: &str| matches!(p.rsplit('/').next(), Some("package.scala" | "package.sc"));
    // Group directories first so package-last ordering remains transitive even
    // when an import map combines parent and nested packages.
    dir_of(a)
        .cmp(dir_of(b))
        .then_with(|| package(a).cmp(&package(b)))
        .then_with(|| a.cmp(b))
}

#[cfg(test)]
mod tests {
    #[test]
    fn nested_packages_have_a_total_package_last_order() {
        let mut paths = vec!["a/package.scala", "a/q/N.scala", "a/z.scala"];
        paths.sort_by(|a, b| super::compare_members(a, b));
        assert_eq!(paths, ["a/z.scala", "a/package.scala", "a/q/N.scala"]);
        for (i, a) in paths.iter().enumerate() {
            for b in &paths[i + 1..] {
                assert!(super::compare_members(a, b).is_lt());
            }
        }
    }
}
