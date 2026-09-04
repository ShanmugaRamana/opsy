use axum::extract::{Path, State};
use axum::Json;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

use crate::db::DbPool;
use crate::error::AppError;

#[derive(Serialize, FromRow)]
pub struct SessionRecord {
    pub session_id: i32,
    pub session_name: String,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Serialize, Deserialize, FromRow)]
pub struct ChatRow {
    pub chat_id: i32,
    pub session_id: i32,
    pub role: String,
    pub chat: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Serialize, Deserialize)]
pub struct ChatTurn {
    pub chat_id: i32,
    pub role: String,
    pub created_at: DateTime<Utc>,
    pub mode: Option<String>,
    pub thinking: Option<String>,
    pub content: Option<String>,
    pub summary: Option<String>,
    pub agents: serde_json::Value,
    pub disk_report: Option<serde_json::Value>,
    pub process_report: Option<serde_json::Value>,
    pub network_report: Option<serde_json::Value>,
    pub commands_run: serde_json::Value,
}

fn parse_chat_turn(row: ChatRow) -> ChatTurn {
    if row.role == "user" {
        return ChatTurn {
            chat_id: row.chat_id,
            role: "user".to_string(),
            created_at: row.created_at,
            mode: None,
            thinking: None,
            content: Some(row.chat),
            summary: None,
            agents: serde_json::json!([]),
            disk_report: None,
            process_report: None,
            network_report: None,
            commands_run: serde_json::json!([]),
        };
    }

    // Try parsing as JSON first if stored as json or fallback to content
    let mut content = None;
    let mut thinking = None;
    let mut mode = Some("general".to_string());
    let mut summary = None;
    let mut disk_report = None;
    let mut process_report = None;
    let mut network_report = None;
    let mut commands_run = serde_json::json!([]);
    let mut agents = serde_json::json!([]);

    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&row.chat) {
        if let Some(m) = val.get("mode").and_then(|v| v.as_str()) {
            mode = Some(m.to_string());
        }
        thinking = val.get("thinking").and_then(|v| v.as_str()).map(|s| s.to_string());
        content = val.get("content").and_then(|v| v.as_str()).map(|s| s.to_string());
        summary = val.get("summary").and_then(|v| v.as_str()).map(|s| s.to_string());
        if let Some(d) = val.get("disk_report") {
            disk_report = Some(d.clone());
        }
        if let Some(p) = val.get("process_report") {
            process_report = Some(p.clone());
        }
        if let Some(n) = val.get("network_report") {
            network_report = Some(n.clone());
        }
        if let Some(c) = val.get("commands_run") {
            commands_run = c.clone();
        }
        if let Some(a) = val.get("agents") {
            agents = a.clone();
        }
    } else {
        content = Some(row.chat);
    }

    ChatTurn {
        chat_id: row.chat_id,
        role: "assistant".to_string(),
        created_at: row.created_at,
        mode,
        thinking,
        content,
        summary,
        agents,
        disk_report,
        process_report,
        network_report,
        commands_run,
    }
}

pub async fn list_sessions(State(pool): State<DbPool>) -> Result<Json<Vec<SessionRecord>>, AppError> {
    let sessions = sqlx::query_as::<_, SessionRecord>(
        r#"
        SELECT session_id, session_name, is_active, created_at, updated_at
        FROM sessions
        ORDER BY updated_at DESC
        "#,
    )
    .fetch_all(&pool)
    .await?;

    Ok(Json(sessions))
}

pub async fn get_session_chats(
    State(pool): State<DbPool>,
    Path(session_id): Path<i32>,
) -> Result<Json<Vec<ChatTurn>>, AppError> {
    let session_exists: Option<(i32,)> = sqlx::query_as("SELECT session_id FROM sessions WHERE session_id = $1")
        .bind(session_id)
        .fetch_optional(&pool)
        .await?;

    if session_exists.is_none() {
        return Err(AppError::NotFound("No such session".to_string()));
    }

    let rows = sqlx::query_as::<_, ChatRow>(
        r#"
        SELECT chat_id, session_id, role, chat, created_at
        FROM chats
        WHERE session_id = $1
        ORDER BY created_at ASC, chat_id ASC
        "#,
    )
    .bind(session_id)
    .fetch_all(&pool)
    .await?;

    let turns = rows.into_iter().map(parse_chat_turn).collect();
    Ok(Json(turns))
}

pub async fn activate_session(
    State(pool): State<DbPool>,
    Path(session_id): Path<i32>,
) -> Result<Json<SessionRecord>, AppError> {
    let mut tx = pool.begin().await?;

    let session = sqlx::query_as::<_, SessionRecord>(
        r#"
        SELECT session_id, session_name, is_active, created_at, updated_at
        FROM sessions
        WHERE session_id = $1
        "#,
    )
    .bind(session_id)
    .fetch_optional(&mut *tx)
    .await?;

    if session.is_none() {
        return Err(AppError::NotFound("No such session".to_string()));
    }

    sqlx::query("UPDATE sessions SET is_active = false WHERE is_active = true")
        .execute(&mut *tx)
        .await?;

    sqlx::query("UPDATE sessions SET is_active = true, updated_at = now() WHERE session_id = $1")
        .bind(session_id)
        .execute(&mut *tx)
        .await?;

    let updated = sqlx::query_as::<_, SessionRecord>(
        r#"
        SELECT session_id, session_name, is_active, created_at, updated_at
        FROM sessions
        WHERE session_id = $1
        "#,
    )
    .bind(session_id)
    .fetch_one(&mut *tx)
    .await?;

    tx.commit().await?;

    Ok(Json(updated))
}
