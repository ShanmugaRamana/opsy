use axum::extract::{Path, State};
use axum::Json;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

use crate::crypto::{decrypt, encrypt};
use crate::db::DbPool;
use crate::error::AppError;

const VALID_PROVIDERS: [&str; 4] = ["anthropic", "openai", "gemini", "groq"];

const PROVIDER_CATALOG: &[(&str, &[(&str, &str)])] = &[
    (
        "groq",
        &[
            ("openai/gpt-oss-120b", "GPT OSS 120B"),
            ("openai/gpt-oss-20b", "GPT OSS 20B"),
            ("qwen/qwen3.6-27b", "Qwen 3.6 27B"),
            ("qwen/qwen3.8-27b", "Qwen 3.8 27B"),
        ],
    ),
    (
        "anthropic",
        &[
            ("claude-opus-5", "Claude Opus 5"),
            ("claude-sonnet-5", "Claude Sonnet 5"),
        ],
    ),
    (
        "openai",
        &[
            ("gpt-5", "GPT-5"),
            ("gpt-5-mini", "GPT-5 mini"),
            ("openai/gpt-oss-120b", "GPT OSS 120B"),
            ("openai/gpt-oss-20b", "GPT OSS 20B"),
        ],
    ),
    (
        "gemini",
        &[
            ("gemini-3.7-flash", "Gemini 3.7 Flash"),
            ("gemini-3.5-flash", "Gemini 3.5 Flash"),
            ("gemini-3.1-pro", "Gemini 3.1 Pro"),
            ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite"),
        ],
    ),
];

#[derive(Deserialize)]
pub struct ApiKeyPayload {
    pub provider: String,
    pub api_key: String,
}

#[derive(Serialize)]
pub struct ApiKeyVerifyResult {
    pub valid: bool,
    pub provider: String,
}

#[derive(Serialize, FromRow)]
pub struct ConfiguredProvider {
    pub provider: String,
    pub key_last4: String,
    pub verified_at: Option<DateTime<Utc>>,
}

async fn verify_provider_key(provider: &str, api_key: &str) -> Result<bool, AppError> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;

    let res = match provider {
        "anthropic" => {
            client
                .get("https://api.anthropic.com/v1/models")
                .header("x-api-key", api_key)
                .header("anthropic-version", "2023-06-01")
                .send()
                .await
        }
        "openai" => {
            client
                .get("https://api.openai.com/v1/models")
                .header("Authorization", format!("Bearer {}", api_key))
                .send()
                .await
        }
        "gemini" => {
            client
                .get(format!(
                    "https://generativelanguage.googleapis.com/v1beta/models?key={}",
                    api_key
                ))
                .send()
                .await
        }
        "groq" => {
            client
                .get("https://api.groq.com/openai/v1/models")
                .header("Authorization", format!("Bearer {}", api_key))
                .send()
                .await
        }
        _ => return Err(AppError::BadRequest(format!("Unknown provider: {}", provider))),
    };

    match res {
        Ok(response) => {
            if response.status().is_success() {
                Ok(true)
            } else if response.status().as_u16() == 401 || response.status().as_u16() == 403 {
                Err(AppError::BadRequest("Invalid API key".to_string()))
            } else {
                Err(AppError::ServiceUnavailable("Could not reach provider".to_string()))
            }
        }
        Err(e) => Err(AppError::ServiceUnavailable(format!("Could not reach provider: {}", e))),
    }
}

pub async fn verify_and_store_key(
    State(pool): State<DbPool>,
    Json(payload): Json<ApiKeyPayload>,
) -> Result<Json<ApiKeyVerifyResult>, AppError> {
    if !VALID_PROVIDERS.contains(&payload.provider.as_str()) {
        return Err(AppError::BadRequest(format!("Unknown provider: {}", payload.provider)));
    }

    verify_provider_key(&payload.provider, &payload.api_key).await?;

    let encrypted = encrypt(&payload.api_key).map_err(|e| AppError::Internal(e))?;
    let last4 = if payload.api_key.len() >= 4 {
        &payload.api_key[payload.api_key.len() - 4..]
    } else {
        &payload.api_key
    };

    sqlx::query(
        r#"
        INSERT INTO byok (provider, api_key_encrypted, key_last4, verified_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (provider) DO UPDATE
        SET api_key_encrypted = EXCLUDED.api_key_encrypted,
            key_last4 = EXCLUDED.key_last4,
            verified_at = now()
        "#,
    )
    .bind(&payload.provider)
    .bind(&encrypted)
    .bind(last4)
    .execute(&pool)
    .await?;

    // Sync model catalog for provider
    sqlx::query("DELETE FROM models WHERE provider = $1")
        .bind(&payload.provider)
        .execute(&pool)
        .await?;

    if let Some((_, entries)) = PROVIDER_CATALOG.iter().find(|(p, _)| *p == payload.provider) {
        for (model_id, display_name) in *entries {
            sqlx::query(
                r#"
                INSERT INTO models (provider, model_id, display_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (provider, model_id) DO NOTHING
                "#,
            )
            .bind(&payload.provider)
            .bind(model_id)
            .bind(display_name)
            .execute(&pool)
            .await?;
        }
    }

    Ok(Json(ApiKeyVerifyResult {
        valid: true,
        provider: payload.provider,
    }))
}

pub async fn delete_key_route(
    State(pool): State<DbPool>,
    Path(provider): Path<String>,
) -> Result<Json<serde_json::Value>, AppError> {
    if !VALID_PROVIDERS.contains(&provider.as_str()) {
        return Err(AppError::BadRequest(format!("Unknown provider: {}", provider)));
    }

    let rows_affected = sqlx::query("DELETE FROM byok WHERE provider = $1")
        .bind(&provider)
        .execute(&pool)
        .await?
        .rows_affected();

    if rows_affected == 0 {
        return Err(AppError::NotFound(format!("No key configured for {}", provider)));
    }

    sqlx::query("DELETE FROM models WHERE provider = $1")
        .bind(&provider)
        .execute(&pool)
        .await?;

    Ok(Json(serde_json::json!({ "deleted": provider })))
}

pub async fn list_configured_keys(
    State(pool): State<DbPool>,
) -> Result<Json<Vec<ConfiguredProvider>>, AppError> {
    let keys = sqlx::query_as::<_, ConfiguredProvider>(
        r#"
        SELECT provider, key_last4, verified_at
        FROM byok
        ORDER BY provider
        "#,
    )
    .fetch_all(&pool)
    .await?;

    Ok(Json(keys))
}

pub async fn get_decrypted_key(pool: &DbPool, provider: &str) -> Option<String> {
    let row: Option<(String,)> = sqlx::query_as("SELECT api_key_encrypted FROM byok WHERE provider = $1")
        .bind(provider)
        .fetch_optional(pool)
        .await
        .ok()?;

    if let Some((encrypted,)) = row {
        decrypt(&encrypted).ok()
    } else {
        None
    }
}
