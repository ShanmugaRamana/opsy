use serde_json::json;
use crate::onboard::domain::UserData;
use crate::shared::error::AppError;

const ALL_AVAILABLE_MODELS: &[(&str, &str)] = &[
    ("qwen 2.5 0.5b", "qwen2.5:0.5b"),
    ("qwen 2.5 1.5b", "qwen2.5:1.5b"),
    ("qwen 2.5 3b", "qwen2.5:3b"),
    ("qwen 2.5 7b", "qwen2.5:7b"),
    ("qwen 2.5 14b", "qwen2.5:14b"),
    ("qwen 2.5 72b", "qwen2.5:72b"),
    ("llama 3.2 1b", "llama3.2:1b"),
    ("llama 3.2 3b", "llama3.2:3b"),
    ("llama 3 8b", "llama3"),
    ("llama 3.3 70b", "llama3.3"),
    ("gemma 2 2b", "gemma2:2b"),
    ("gemma 2 9b", "gemma2:9b"),
    ("phi 3.5 mini", "phi3.5"),
    ("mistral 7b", "mistral"),
    ("mistral nemo 12b", "mistral-nemo"),
    ("codestral 22b", "codestral"),
    ("command r 35b", "command-r"),
    ("command r+ 104b", "command-r-plus"),
    ("mixtral 8x7b", "mixtral"),
    ("smollm2 1.7b", "smollm2:1.7b"),
];

fn get_ollama_tag(model_name: &str) -> String {
    let name_lower = model_name.to_lowercase();
    for (key, tag) in ALL_AVAILABLE_MODELS {
        if name_lower.contains(key) {
            return tag.to_string();
        }
    }
    model_name.to_string()
}

pub async fn generate_reply(user_data: &UserData, prompt: &str) -> Result<String, AppError> {
    // 1. If Local Ollama model is active
    if let Some(ref model) = user_data.active_model {
        let ollama_tag = get_ollama_tag(model);
        let client = reqwest::Client::new();
        let payload = json!({
            "model": ollama_tag,
            "prompt": prompt,
            "stream": false
        });

        match client.post("http://localhost:11434/api/generate")
            .json(&payload)
            .send()
            .await {
                Ok(resp) => {
                    if resp.status().is_success() {
                        if let Ok(body) = resp.json::<serde_json::Value>().await {
                            if let Some(response_text) = body.get("response").and_then(|r| r.as_str()) {
                                return Ok(response_text.to_string());
                            }
                        }
                    }
                }
                Err(e) => {
                    tracing::warn!("Ollama request error: {}", e);
                }
            }
    }

    // 2. If OpenAI / Anthropic BYOK key is set
    if let Some(ref api_config) = user_data.api_key {
        if api_config.provider.to_lowercase() == "openai" {
            let client = reqwest::Client::new();
            let payload = json!({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are Opsy, an AI assistant."},
                    {"role": "user", "content": prompt}
                ]
            });

            if let Ok(resp) = client.post("https://api.openai.com/v1/chat/completions")
                .header("Authorization", format!("Bearer {}", api_config.key))
                .json(&payload)
                .send()
                .await {
                    if let Ok(body) = resp.json::<serde_json::Value>().await {
                        if let Some(content) = body["choices"][0]["message"]["content"].as_str() {
                            return Ok(content.to_string());
                        }
                    }
                }
        }
    }

    // Fallback response if offline/unconfigured
    Ok(format!(
        "Hello! I am Opsy. I received your message: \"{}\". (Configure a local model via Ollama or an API key in settings to enable live responses)",
        prompt
    ))
}
