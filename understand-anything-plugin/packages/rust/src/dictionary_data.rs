//! Runtime dictionary snapshots. Downloads belong to explicit maintenance tooling.
use crate::{Error, Result};
use flate2::read::GzDecoder;
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::{env, fs, io::Read, path::PathBuf};

fn cache_dir() -> Option<PathBuf> {
    env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|p| PathBuf::from(p).join(".cache")))
        .map(|p| p.join("understand-anything/dictionaries"))
}

pub fn directory() -> PathBuf {
    if let Some(path) = env::var_os("UA_DICTIONARY_DIR") {
        return PathBuf::from(path);
    }
    if let Some(path) = cache_dir().filter(|p| p.join("current.json").is_file()) {
        return path;
    }
    if let Ok(executable) = env::current_exe()
        && let Some(parent) = executable.parent().and_then(|p| p.parent())
    {
        let candidate = parent.join("dictionaries");
        if executable
            .parent()
            .is_some_and(|p| p.file_name().is_some_and(|n| n == "bin"))
            || candidate.join("current.json").is_file()
        {
            return candidate;
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("dictionaries")
}

pub struct Snapshot {
    pub manifest: Value,
    root: PathBuf,
}
impl Snapshot {
    pub fn open() -> Result<Self> {
        Self::open_at(directory()).map_err(|error| Error::Invalid(format!(
            "English/technical dictionary is missing or corrupt: {error}. Run the plugin dictionary updater or reinstall; no runtime download is attempted.")))
    }
    pub fn open_at(directory: PathBuf) -> Result<Self> {
        let pointer: Value = serde_json::from_slice(&fs::read(directory.join("current.json"))?)?;
        let generation = pointer["generation"].as_str().unwrap_or("");
        if generation.len() != 64 || !generation.bytes().all(|c| c.is_ascii_hexdigit()) {
            return Err(Error::Invalid("invalid dictionary generation".into()));
        }
        let root = directory.join(generation);
        let raw = fs::read(root.join("manifest.json"))?;
        if crate::query_dictionary::hash(&raw) != generation {
            return Err(Error::Invalid(
                "dictionary manifest checksum mismatch".into(),
            ));
        }
        let manifest: Value = serde_json::from_slice(&raw)?;
        if manifest["version"] != 1 {
            return Err(Error::Invalid("unsupported dictionary schema".into()));
        }
        Ok(Self { manifest, root })
    }
    pub fn load<T: DeserializeOwned>(&self, name: &str) -> Result<T> {
        if !["cspell.json.gz", "lemmas.json.gz"].contains(&name) {
            return Err(Error::Invalid("invalid dictionary filename".into()));
        }
        let raw = fs::read(self.root.join(name))?;
        if Some(crate::query_dictionary::hash(&raw).as_str())
            != self.manifest["files"][name].as_str()
        {
            return Err(Error::Invalid(format!(
                "dictionary checksum mismatch: {name}"
            )));
        }
        let mut decoded = Vec::new();
        GzDecoder::new(raw.as_slice())
            .take(64 * 1024 * 1024 + 1)
            .read_to_end(&mut decoded)?;
        if decoded.len() > 64 * 1024 * 1024 {
            return Err(Error::Invalid("dictionary size limit exceeded".into()));
        }
        Ok(serde_json::from_slice(&decoded)?)
    }
}

/// Paths are configured once at installation; runtime never probes package managers.
pub struct Sources {
    config: Value,
    config_path: PathBuf,
    pub snapshot_dir: Option<PathBuf>,
}
impl Sources {
    pub fn open() -> Result<Self> {
        let user = env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .or_else(|| env::var_os("HOME").map(|p| PathBuf::from(p).join(".config")))
            .map(|p| p.join("understand-anything/dictionaries.json"));
        let packaged = env::current_exe().ok().is_some_and(|p| {
            p.parent()
                .is_some_and(|p| p.file_name().is_some_and(|n| n == "bin"))
        });
        let executable = env::current_exe().ok().and_then(|p| {
            p.parent()?
                .parent()
                .map(|p| p.join("dictionary-config.json"))
        });
        let path = env::var_os("UA_DICTIONARY_CONFIG")
            .map(PathBuf::from)
            .or_else(|| executable.filter(|p| p.is_file()))
            .or_else(|| {
                if packaged {
                    return None;
                }
                let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("dictionary-config.json");
                path.is_file().then_some(path)
            })
            .or_else(|| user.filter(|p| p.is_file()));
        let config_path = path.clone().unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("dictionary-config.json")
        });
        let config = if let Some(path) = path {
            let bytes = fs::read(&path).map_err(|error| repair_error(error, &path))?;
            let value: Value =
                serde_json::from_slice(&bytes).map_err(|error| repair_error(error, &path))?;
            if value["version"] != 1 {
                return Err(Error::Invalid("unsupported dictionary config".into()));
            }
            value
        } else {
            serde_json::json!({})
        };
        let snapshot_dir = env::var_os("UA_DICTIONARY_DIR")
            .map(PathBuf::from)
            .or_else(|| config["snapshot"].as_str().map(PathBuf::from))
            .or_else(|| {
                if config.get("version").is_some() {
                    return None;
                }
                let path = directory();
                path.join("current.json").is_file().then_some(path)
            });
        Ok(Self {
            config,
            config_path,
            snapshot_dir,
        })
    }
    pub fn lemmas(&self) -> Result<crate::query_terms::Lemmas> {
        self.read_lemmas()
            .map_err(|error| repair_error(error, &self.config_path))
    }
    fn read_lemmas(&self) -> Result<crate::query_terms::Lemmas> {
        if let Some(lookup) = self.config["lemminflect"]["lookup"].as_str() {
            let mut result = crate::query_terms::Lemmas::new();
            for (path, overrides) in [
                (lookup, false),
                (
                    self.config["lemminflect"]["overrides"]
                        .as_str()
                        .ok_or_else(|| Error::Invalid("missing lemma overrides path".into()))?,
                    true,
                ),
            ] {
                for line in read_text(std::path::Path::new(path))?.lines() {
                    let line = line.trim();
                    if line.is_empty() || line.starts_with('#') {
                        continue;
                    }
                    let columns: Vec<_> = line.split(',').collect();
                    if columns.len() != 3 {
                        return Err(Error::Invalid("invalid installed lemma data".into()));
                    }
                    let pos = if columns[1].eq_ignore_ascii_case("modal") {
                        "AUX".into()
                    } else {
                        columns[1].to_uppercase()
                    };
                    let forms = if overrides {
                        vec![columns[2].to_owned()]
                    } else {
                        columns[2].split('/').map(str::to_owned).collect()
                    };
                    result
                        .entry(columns[0].to_owned())
                        .or_default()
                        .insert(pos, forms);
                }
            }
            if result.is_empty() {
                return Err(Error::Invalid("installed lemma dictionary is empty".into()));
            }
            return Ok(result);
        }
        if let Some(path) = &self.snapshot_dir {
            return Snapshot::open_at(path.clone())?.load("lemmas.json.gz");
        }
        eprintln!(
            "No lemma dictionary configured; using built-in query rules. Run configure_dictionaries.py during plugin installation."
        );
        Ok(Default::default())
    }
    pub fn technical(
        &self,
        selected: &std::collections::BTreeSet<String>,
    ) -> Result<std::collections::BTreeMap<String, Vec<String>>> {
        self.read_technical(selected)
            .map_err(|error| repair_error(error, &self.config_path))
    }
    fn read_technical(
        &self,
        selected: &std::collections::BTreeSet<String>,
    ) -> Result<std::collections::BTreeMap<String, Vec<String>>> {
        let mut result = std::collections::BTreeMap::new();
        let mut fallback: Option<std::collections::BTreeMap<String, Vec<String>>> = None;
        for name in selected {
            if let Some(paths) = self.config["cspell"][name].as_array() {
                let mut words = std::collections::BTreeSet::new();
                let mut forbidden = std::collections::BTreeSet::new();
                for path in paths {
                    let path = path
                        .as_str()
                        .ok_or_else(|| Error::Invalid("invalid CSpell path".into()))?;
                    for line in read_text(std::path::Path::new(path))?.lines() {
                        let line = line.trim();
                        if let Some(word) = line.strip_prefix('!') {
                            forbidden.insert(crate::query_terms::normalized(word));
                        } else if !line.starts_with('#')
                            && crate::query_terms::tokens(line) == [line]
                        {
                            words.insert(line.to_owned());
                        }
                    }
                }
                words.retain(|w| !forbidden.contains(&crate::query_terms::normalized(w)));
                result.insert(name.clone(), words.into_iter().collect());
            } else {
                if fallback.is_none() {
                    fallback = Some(if let Some(path) = &self.snapshot_dir {
                        Snapshot::open_at(path.clone())?.load("cspell.json.gz")?
                    } else {
                        Default::default()
                    });
                }
                if let Some(words) = fallback.as_ref().unwrap().get(name) {
                    result.insert(name.clone(), words.clone());
                } else {
                    eprintln!(
                        "CSpell dictionary unavailable: {name}; using graph vocabulary for this dictionary."
                    );
                }
            }
        }
        Ok(result)
    }
}
fn read_text(path: &std::path::Path) -> Result<String> {
    let file = fs::File::open(path)?;
    let reader: Box<dyn Read> = if path.extension().is_some_and(|e| e == "gz") {
        Box::new(GzDecoder::new(file))
    } else {
        Box::new(file)
    };
    let mut bytes = Vec::new();
    reader.take(64 * 1024 * 1024 + 1).read_to_end(&mut bytes)?;
    if bytes.len() > 64 * 1024 * 1024 {
        return Err(Error::Invalid("dictionary size limit exceeded".into()));
    }
    String::from_utf8(bytes).map_err(|e| Error::Invalid(e.to_string()))
}

fn repair_error(error: impl std::fmt::Display, config: &std::path::Path) -> Error {
    let quoted = format!("'{}'", config.display().to_string().replace('\'', "'\\''"));
    Error::Invalid(format!(
        "Dictionary access failed: {error}. Configuration: {}. Update lemminflect.lookup/overrides and cspell dictionary file paths in this JSON to the current system locations, or rerun configure_dictionaries.py with --lemma-resources /new/lemminflect/resources or --cspell-root /new/node_modules. To download and use latest repo-local data instead, set PLUGIN_ROOT to the plugin source directory and run: python3 \"$PLUGIN_ROOT/scripts/configure_dictionaries.py\" --plugin-root \"$PLUGIN_ROOT\" --config {quoted} --prefer-local --local-dir \"$PLUGIN_ROOT/packages/rust/dictionaries\". Then run /understand --full. Runtime does not download or modify system packages.",
        config.display()
    ))
}
