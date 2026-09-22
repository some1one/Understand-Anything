//! Opt-in embedding generation with an injectable blocking client.
use crate::{Error, Result, strings};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    env, fs,
    path::{Path, PathBuf},
};
pub const DEFAULT_MODEL: &str = "text-embedding-3-small";
pub const DEFAULT_BASE_URL: &str = "https://api.openai.com/v1";
pub trait EmbeddingClient {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f64>>>;
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EmbeddingResult {
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub dim: usize,
    #[serde(default)]
    pub embeddings: BTreeMap<String, Vec<f64>>,
}
pub fn node_text(node: &Value) -> String {
    [
        node["name"].as_str().unwrap_or("").to_owned(),
        node["summary"].as_str().unwrap_or("").to_owned(),
        strings(&node["tags"]).join(" "),
    ]
    .iter()
    .map(|s| s.trim())
    .filter(|s| !s.is_empty())
    .collect::<Vec<_>>()
    .join("\n")
}
pub fn build_embeddings(
    nodes: &[Value],
    client: &dyn EmbeddingClient,
    model: &str,
    batch_size: usize,
) -> Result<EmbeddingResult> {
    let texts: Vec<_> = nodes
        .iter()
        .filter_map(|n| {
            let id = n["id"].as_str().unwrap_or("");
            let text = node_text(n);
            if id.is_empty() || text.is_empty() {
                None
            } else {
                Some((id, text))
            }
        })
        .collect();
    let mut embeddings = BTreeMap::new();
    let mut dim = None;
    for batch in texts.chunks(batch_size.max(1)) {
        let vectors = client.embed(&batch.iter().map(|(_, s)| s.clone()).collect::<Vec<_>>())?;
        for ((id, _), v) in batch.iter().zip(vectors) {
            dim.get_or_insert(v.len());
            embeddings.insert((*id).into(), v);
        }
    }
    Ok(EmbeddingResult {
        model: model.into(),
        dim: dim.unwrap_or(0),
        embeddings,
    })
}
pub fn save_embeddings(path: &Path, result: &EmbeddingResult) -> Result<()> {
    fs::write(path, serde_json::to_string_pretty(result)?)?;
    Ok(())
}
pub fn load_embeddings(path: &Path) -> Result<Option<EmbeddingResult>> {
    if !path.is_file() {
        return Ok(None);
    }
    Ok(Some(serde_json::from_slice(&fs::read(path)?)?))
}
fn setting(name: &str, default: &str) -> String {
    env::var(name)
        .ok()
        .map(|s| s.trim().to_owned())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| default.into())
}
pub fn embeddings_enabled() -> bool {
    !setting("UNDERSTAND_EMBEDDINGS_API_KEY", "").is_empty()
}
pub struct HttpEmbeddingClient {
    client: reqwest::blocking::Client,
    api_key: String,
    pub model: String,
    base_url: String,
}
impl HttpEmbeddingClient {
    pub fn new(api_key: String, model: String, base_url: String) -> Result<Self> {
        Ok(Self {
            client: reqwest::blocking::Client::builder().build()?,
            api_key,
            model,
            base_url: base_url.trim_end_matches('/').into(),
        })
    }
}
impl EmbeddingClient for HttpEmbeddingClient {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f64>>> {
        let payload: Value = self
            .client
            .post(format!("{}/embeddings", self.base_url))
            .bearer_auth(&self.api_key)
            .json(&json!({"model":self.model,"input":texts}))
            .send()?
            .error_for_status()?
            .json()?;
        let mut data = payload["data"]
            .as_array()
            .ok_or_else(|| Error::Invalid("embedding response missing data".into()))?
            .clone();
        data.sort_by_key(|v| v["index"].as_i64().unwrap_or(0));
        data.iter()
            .map(|d| Ok(serde_json::from_value(d["embedding"].clone())?))
            .collect()
    }
}
pub fn default_client() -> Result<HttpEmbeddingClient> {
    let key = setting("UNDERSTAND_EMBEDDINGS_API_KEY", "");
    if key.is_empty() {
        return Err(Error::Invalid(
            "UNDERSTAND_EMBEDDINGS_API_KEY is not set".into(),
        ));
    }
    HttpEmbeddingClient::new(
        key,
        setting("UNDERSTAND_EMBEDDINGS_MODEL", DEFAULT_MODEL),
        setting("UNDERSTAND_EMBEDDINGS_BASE_URL", DEFAULT_BASE_URL),
    )
}
pub fn generate_and_save(
    root: &Path,
    nodes: &[Value],
    client: Option<&dyn EmbeddingClient>,
    model: Option<&str>,
) -> Result<PathBuf> {
    let default;
    let client = if let Some(c) = client {
        c
    } else {
        default = default_client()?;
        &default
    };
    let model = model
        .map(str::to_owned)
        .unwrap_or_else(|| setting("UNDERSTAND_EMBEDDINGS_MODEL", DEFAULT_MODEL));
    let result = build_embeddings(nodes, client, &model, 64)?;
    let out = root.join(".understand-anything/embeddings.json");
    save_embeddings(&out, &result)?;
    Ok(out)
}
