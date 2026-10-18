pub mod github;
pub mod github_widget;
pub mod hub;
pub mod kaggle;
pub mod kaggle_datos;
pub mod kaggle_pdf;
pub mod kaggle_profesor;
pub mod kaggle_red;
pub mod youtube;
pub mod youtube_profesor;

use bytes::Bytes;
use futures_util::Stream;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use thiserror::Error;
use tracing::{debug, warn};

#[derive(Error, Debug)]
pub enum OllamaError {
    #[error("Error de conexión con Ollama en {0}: {1}")]
    Connection(String, String),
    #[error("Ollama respondió con error HTTP {0}: {1}")]
    Http(u16, String),
    #[error("Error serializando JSON de Ollama: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Error de stream de Ollama: {0}")]
    Stream(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelDetails {
    #[serde(default)]
    pub parent_model: Option<String>,
    #[serde(default)]
    pub format: Option<String>,
    #[serde(default)]
    pub family: Option<String>,
    #[serde(default)]
    pub families: Option<Vec<String>>,
    #[serde(default)]
    pub parameter_size: Option<String>,
    #[serde(default)]
    pub quantization_level: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaModel {
    pub name: String,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub modified_at: Option<String>,
    #[serde(default)]
    pub size: Option<u64>,
    #[serde(default)]
    pub digest: Option<String>,
    #[serde(default)]
    pub details: Option<ModelDetails>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaTagsResponse {
    #[serde(default)]
    pub models: Vec<OllamaModel>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaPsResponse {
    #[serde(default)]
    pub models: Vec<OllamaModel>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaVersionResponse {
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AiStatusResponse {
    pub status: String,
    pub ollama_active: bool,
    pub version: String,
    pub models: Vec<String>,
}

/// Límite de las consultas cortas (versión, modelos, cargados, borrar)
const CONSULTA: Duration = Duration::from_secs(15);

#[derive(Debug, Clone)]
pub struct OllamaClient {
    pub base_url: String,
    pub client: Client,
}

impl OllamaClient {
    pub fn new(base_url: Option<String>) -> Self {
        let url = base_url
            .unwrap_or_else(|| "http://127.0.0.1:11434".to_string())
            .trim_end_matches('/')
            .to_string();

        // Sin tiempo límite total: en reqwest incluye leer el cuerpo, y cortaba a los 120 s el chat en streaming y la
        // descarga de modelos grandes. Las consultas cortas llevan su propio límite (CONSULTA).
        let client = Client::builder()
            .connect_timeout(Duration::from_millis(1500))
            .pool_idle_timeout(Duration::from_secs(90))
            .build()
            .unwrap_or_default();

        Self {
            base_url: url,
            client,
        }
    }

    pub async fn check_status(&self) -> AiStatusResponse {
        let ver_url = format!("{}/api/version", self.base_url);
        let tags_url = format!("{}/api/tags", self.base_url);

        let ver_fut = self.client.get(&ver_url).timeout(CONSULTA).send();
        let tags_fut = self.client.get(&tags_url).timeout(CONSULTA).send();

        let (ver_res, tags_res) = tokio::join!(ver_fut, tags_fut);

        let version = match ver_res {
            Ok(resp) if resp.status().is_success() => {
                resp.json::<OllamaVersionResponse>()
                    .await
                    .map(|v| v.version)
                    .unwrap_or_else(|_| "desconocida".to_string())
            }
            _ => "?".to_string(),
        };

        let (models, is_active) = match tags_res {
            Ok(resp) if resp.status().is_success() => {
                if let Ok(tags) = resp.json::<OllamaTagsResponse>().await {
                    let names: Vec<String> = tags.models.into_iter().map(|m| m.name).collect();
                    (names, true)
                } else {
                    (Vec::new(), true)
                }
            }
            _ => (Vec::new(), false),
        };

        AiStatusResponse {
            status: if is_active { "running".to_string() } else { "offline".to_string() },
            ollama_active: is_active,
            version,
            models,
        }
    }

    pub async fn get_models(&self) -> Result<Vec<String>, OllamaError> {
        let url = format!("{}/api/tags", self.base_url);
        let resp = self
            .client
            .get(&url)
            .timeout(CONSULTA)
            .send()
            .await
            .map_err(|e| OllamaError::Connection(url.clone(), e.to_string()))?;

        if !resp.status().is_success() {
            return Err(OllamaError::Http(resp.status().as_u16(), resp.status().to_string()));
        }

        let tags: OllamaTagsResponse = resp
            .json()
            .await
            .map_err(|e| OllamaError::Connection(url, e.to_string()))?;

        Ok(tags.models.into_iter().map(|m| m.name).collect())
    }

    pub async fn get_detailed_models(&self) -> Result<Vec<OllamaModel>, OllamaError> {
        let url = format!("{}/api/tags", self.base_url);
        let resp = self
            .client
            .get(&url)
            .timeout(CONSULTA)
            .send()
            .await
            .map_err(|e| OllamaError::Connection(url.clone(), e.to_string()))?;

        if !resp.status().is_success() {
            return Err(OllamaError::Http(resp.status().as_u16(), resp.status().to_string()));
        }

        let tags: OllamaTagsResponse = resp
            .json()
            .await
            .map_err(|e| OllamaError::Connection(url, e.to_string()))?;

        Ok(tags.models)
    }

    pub async fn get_running_models(&self) -> Result<Vec<OllamaModel>, OllamaError> {
        let url = format!("{}/api/ps", self.base_url);
        let resp = self
            .client
            .get(&url)
            .timeout(CONSULTA)
            .send()
            .await
            .map_err(|e| OllamaError::Connection(url.clone(), e.to_string()))?;

        if !resp.status().is_success() {
            return Err(OllamaError::Http(resp.status().as_u16(), resp.status().to_string()));
        }

        let ps: OllamaPsResponse = resp
            .json()
            .await
            .map_err(|e| OllamaError::Connection(url, e.to_string()))?;

        Ok(ps.models)
    }

    pub async fn delete_model(&self, model: &str) -> Result<bool, OllamaError> {
        let url = format!("{}/api/delete", self.base_url);
        let resp = self
            .client
            .delete(&url)
            .json(&serde_json::json!({ "model": model }))
            .timeout(CONSULTA)
            .send()
            .await
            .map_err(|e| OllamaError::Connection(url.clone(), e.to_string()))?;

        Ok(resp.status().is_success())
    }

    pub async fn stream_pull(
        &self,
        model: &str,
    ) -> Result<impl Stream<Item = Result<Bytes, reqwest::Error>>, OllamaError> {
        let url = format!("{}/api/pull", self.base_url);
        let resp = self
            .client
            .post(&url)
            .json(&serde_json::json!({ "model": model, "stream": true }))
            .send()
            .await
            .map_err(|e| OllamaError::Connection(url.clone(), e.to_string()))?;

        if !resp.status().is_success() {
            return Err(OllamaError::Http(resp.status().as_u16(), resp.status().to_string()));
        }

        Ok(resp.bytes_stream())
    }

    pub async fn stream_chat(
        &self,
        mut payload: serde_json::Value,
    ) -> Result<impl Stream<Item = Result<Bytes, reqwest::Error>>, OllamaError> {
        // Asegurar que el stream esté activado para latencia cero
        if let Some(obj) = payload.as_object_mut() {
            obj.insert("stream".to_string(), serde_json::Value::Bool(true));
        }

        let url = format!("{}/api/chat", self.base_url);
        debug!("Iniciando streaming SSE Ollama en {}", url);

        let resp = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| OllamaError::Connection(url.clone(), e.to_string()))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let err_body = resp.text().await.unwrap_or_default();
            warn!("Ollama chat falló con status {}: {}", status, err_body);
            return Err(OllamaError::Http(status.as_u16(), err_body));
        }

        Ok(resp.bytes_stream())
    }
}

