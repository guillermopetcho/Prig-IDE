use prig_integrations::{OllamaClient, OllamaTagsResponse};

#[tokio::test]
async fn test_client_initialization() {
    let client = OllamaClient::new(None);
    assert_eq!(client.base_url, "http://127.0.0.1:11434");

    let client_custom = OllamaClient::new(Some("http://localhost:11435/".to_string()));
    assert_eq!(client_custom.base_url, "http://localhost:11435");
}

#[tokio::test]
async fn test_check_status_offline_graceful() {
    // Puerto que no está en uso
    let client = OllamaClient::new(Some("http://127.0.0.1:41981".to_string()));
    let status = client.check_status().await;

    assert_eq!(status.status, "offline");
    assert!(!status.ollama_active);
    assert_eq!(status.version, "?");
    assert!(status.models.is_empty());
}

#[test]
fn test_tags_response_deserialization() {
    let json_data = r#"{
      "models": [
        {
          "name": "llama3:latest",
          "model": "llama3:latest",
          "modified_at": "2026-10-10T12:00:00Z",
          "size": 4661224676,
          "digest": "sha256:abc12345",
          "details": {
            "format": "gguf",
            "family": "llama",
            "parameter_size": "8B",
            "quantization_level": "Q4_0"
          }
        }
      ]
    }"#;

    let parsed: OllamaTagsResponse = serde_json::from_str(json_data).unwrap();
    assert_eq!(parsed.models.len(), 1);
    let m = &parsed.models[0];
    assert_eq!(m.name, "llama3:latest");
    assert_eq!(m.size, Some(4661224676));
    let details = m.details.as_ref().unwrap();
    assert_eq!(details.family.as_deref(), Some("llama"));
    assert_eq!(details.parameter_size.as_deref(), Some("8B"));
}

