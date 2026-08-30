use axum::extract::{Path, State};
use axum::Json;
use serde::Deserialize;
use tracing::info;

use crate::chat::commands::{CreateChatSessionCommand, SendChatMessageCommand};
use crate::chat::domain::{ChatMessage, ChatSession};
use crate::chat::queries::{GetChatSessionQuery, GetChatSessionsQuery};
use crate::shared::bus::{CommandBus, QueryBus};
use crate::shared::error::AppError;

#[derive(Clone)]
pub struct ChatState {
    pub command_bus: CommandBus,
    pub query_bus: QueryBus,
}

pub async fn list_sessions_handler(
    State(state): State<ChatState>,
) -> Result<Json<Vec<ChatSession>>, AppError> {
    info!("GET /chat/sessions requested");
    let sessions = state.query_bus.dispatch(GetChatSessionsQuery).await?;
    Ok(Json(sessions))
}

pub async fn get_session_handler(
    State(state): State<ChatState>,
    Path(session_id): Path<String>,
) -> Result<Json<ChatSession>, AppError> {
    info!("GET /chat/sessions/{} requested", session_id);
    let session = state
        .query_bus
        .dispatch(GetChatSessionQuery { session_id: session_id.clone() })
        .await?
        .ok_or_else(|| AppError::NotFound(format!("Session {} not found", session_id)))?;
    Ok(Json(session))
}

#[derive(Deserialize)]
pub struct CreateSessionRequest {
    pub title: Option<String>,
}

pub async fn create_session_handler(
    State(state): State<ChatState>,
    Json(payload): Json<CreateSessionRequest>,
) -> Result<Json<ChatSession>, AppError> {
    info!("POST /chat/sessions requested");
    let session_id = format!("sess_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    let title = payload.title.unwrap_or_else(|| "New Chat".to_string());
    let new_session = ChatSession {
        id: session_id,
        title,
        created_at: "Just now".to_string(),
        messages: Vec::new(),
    };

    let created = state
        .command_bus
        .dispatch(CreateChatSessionCommand { session: new_session })
        .await?;
    Ok(Json(created))
}

#[derive(Deserialize)]
pub struct SendMessageRequest {
    pub text: String,
}

#[derive(serde::Serialize)]
pub struct SendMessageResponse {
    pub session: ChatSession,
    pub reply: ChatMessage,
}

pub async fn send_message_handler(
    State(state): State<ChatState>,
    Path(session_id): Path<String>,
    Json(payload): Json<SendMessageRequest>,
) -> Result<Json<SendMessageResponse>, AppError> {
    info!("POST /chat/sessions/{}/messages requested", session_id);
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
    let timestamp = format!("{:02}:{:02}", (now / 3600) % 24, (now / 60) % 60);

    let user_message = ChatMessage {
        id: format!("msg_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis()),
        sender: "user".to_string(),
        text: payload.text,
        timestamp,
    };

    let (session, reply) = state
        .command_bus
        .dispatch(SendChatMessageCommand {
            session_id,
            user_message,
        })
        .await?;

    Ok(Json(SendMessageResponse { session, reply }))
}
