use axum::extract::State;
use axum::Json;
use serde::Serialize;
use sqlx::FromRow;

use crate::db::DbPool;
use crate::error::AppError;

#[derive(Serialize, FromRow)]
pub struct ModelRecord {
    pub provider: String,
    pub provider_display_name: Option<String>,
    pub model_id: String,
    pub display_name: String,
}

pub fn provider_display_name(p: &str) -> String {
    match p {
        "groq" => "Groq".to_string(),
        "anthropic" => "Anthropic".to_string(),
        "openai" => "OpenAI".to_string(),
        "gemini" => "Gemini".to_string(),
        "ollama" => "Ollama".to_string(),
        _ => p.to_string(),
    }
}

pub async fn list_all_models(
    State(pool): State<DbPool>,
) -> Result<Json<Vec<ModelRecord>>, AppError> {
    let mut rows = sqlx::query_as::<_, ModelRecord>(
        r#"
        SELECT provider, NULL as provider_display_name, model_id, display_name
        FROM models
        ORDER BY provider, display_name
        "#,
    )
    .fetch_all(&pool)
    .await?;

    for row in &mut rows {
        row.provider_display_name = Some(provider_display_name(&row.provider));
    }

    Ok(Json(rows))
}
