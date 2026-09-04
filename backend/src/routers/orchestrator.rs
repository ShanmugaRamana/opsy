use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::Json;
use futures::{SinkExt, StreamExt};
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{error, info};

use crate::config::Config;
use crate::db::DbPool;
use crate::error::AppError;
use crate::routers::byok::get_decrypted_key;

#[derive(Clone, Debug, Deserialize)]
pub struct OrchestratorRequest {
    pub provider: String,
    pub model_id: String,
    pub message: String,
    pub session_id: Option<i32>,
    #[serde(default)]
    pub is_retry: bool,
}

#[derive(Serialize)]
pub struct OrchestratorResponse {
    pub provider: String,
    pub model_id: String,
    pub session_id: Option<i32>,
    pub mode: String,
    pub modes: Vec<String>,
    pub summary: Option<String>,
    pub agents: serde_json::Value,
    pub thinking: Option<String>,
    pub content: Option<String>,
    pub raw_xml: Option<String>,
    pub disk_report: Option<serde_json::Value>,
    pub process_report: Option<serde_json::Value>,
    pub network_report: Option<serde_json::Value>,
    pub commands_run: serde_json::Value,
}

#[derive(Deserialize)]
pub struct PermissionDecision {
    pub decision: String,
}

pub struct PermissionEntry {
    pub argv: Vec<String>,
    pub reason: String,
    pub approved: Option<bool>,
}

lazy_static! {
    pub static ref PERMISSIONS: Arc<Mutex<HashMap<String, PermissionEntry>>> = Arc::new(Mutex::new(HashMap::new()));
}

pub async fn decide_permission(
    Path(request_id): Path<String>,
    Json(payload): Json<PermissionDecision>,
) -> Result<Json<serde_json::Value>, AppError> {
    let decision = payload.decision.trim().to_lowercase();
    let is_approved = match decision.as_str() {
        "approve" => true,
        "deny" => false,
        _ => return Err(AppError::BadRequest("decision must be 'approve' or 'deny'".to_string())),
    };

    let mut perms = PERMISSIONS.lock().await;
    if let Some(entry) = perms.get_mut(&request_id) {
        if entry.approved.is_some() {
            return Err(AppError::Conflict("That permission request was already answered.".to_string()));
        }
        entry.approved = Some(is_approved);
        Ok(Json(serde_json::json!({
            "request_id": request_id,
            "decision": decision
        })))
    } else {
        Err(AppError::NotFound("No such permission request, or it already expired.".to_string()))
    }
}

pub async fn list_agents_catalog() -> Json<serde_json::Value> {
    Json(serde_json::json!([
        {
            "name": "disk",
            "description": "Answers disk and storage questions by running read-only diagnostic commands.",
            "ws_path": "/linux/agents/disk/ws"
        },
        {
            "name": "process",
            "description": "Answers process and service questions by running read-only diagnostic commands.",
            "ws_path": "/linux/agents/process/ws"
        },
        {
            "name": "network",
            "description": "Answers network questions by running read-only diagnostic commands.",
            "ws_path": "/linux/agents/network/ws"
        },
        {
            "name": "base",
            "description": "General system diagnostics and conversation.",
            "ws_path": "/linux/agents/base/ws"
        }
    ]))
}

pub async fn list_tools_catalog() -> Json<serde_json::Value> {
    Json(serde_json::json!([
        {
            "name": "disk",
            "description": "Read-only disk and storage diagnostic commands.",
            "catalog_path": "/linux/tools/disk/"
        },
        {
            "name": "process",
            "description": "Read-only process, load and service observations.",
            "catalog_path": "/linux/tools/process/"
        },
        {
            "name": "network",
            "description": "Read-only network diagnostic commands.",
            "catalog_path": "/linux/tools/network/"
        },
        {
            "name": "system",
            "description": "Read-only system information observations.",
            "catalog_path": "/linux/tools/system/"
        },
        {
            "name": "command",
            "description": "Runs a read-only command the user explicitly approved.",
            "catalog_path": "/linux/tools/command/"
        }
    ]))
}

pub async fn list_memory_catalog() -> Json<serde_json::Value> {
    Json(serde_json::json!([
        {
            "name": "short-term",
            "description": "The last 3 completed turns of a session, as conversation context for the next one.",
            "catalog_path": "/linux/memory/short-term/"
        }
    ]))
}

pub async fn describe_supervisor() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "name": "supervisor",
        "description": "Plans which agents answer a message and composes reports.",
        "catalog_path": "/linux/orchestrator/supervisor/",
        "routes": {
            "POST /linux/orchestrator/supervisor/plan": "which agents should answer a message",
            "POST /linux/orchestrator/supervisor/compose": "one paragraph over several agents' reports"
        }
    }))
}

// Stream LLM response
pub async fn execute_llm_call(
    config: &Config,
    provider: &str,
    api_key: Option<&str>,
    model_id: &str,
    user_message: &str,
) -> Result<String, AppError> {
    let client = reqwest::Client::new();
    let sys_context = crate::system_tools::get_system_context(user_message);

    let system_prompt = format!(
        r#"You are Zyros, an intelligent AI Linux assistant that runs directly on the user's Linux machine.

CRITICAL INSTRUCTIONS:
1. You have direct live access to the user's system diagnostics. NEVER say "I am an AI and cannot check your system", "I don't have access to your machine", or tell the user to manually run commands themselves when they ask what their OS, RAM, disk, IP, CPU, processes, or status is.
2. Directly answer their question using the live system context provided below.
3. Be concise, direct, and factual. Lead with the exact answer first.

LIVE SYSTEM CONTEXT:
{}
"#,
        sys_context
    );

    if provider == "ollama" {
        let res = client
            .post(format!("{}/api/chat", config.ollama_base_url))
            .json(&serde_json::json!({
                "model": model_id,
                "messages": [
                    { "role": "system", "content": &system_prompt },
                    { "role": "user", "content": user_message }
                ],
                "stream": false
            }))
            .send()
            .await
            .map_err(|e| AppError::ServiceUnavailable(format!("Ollama error: {}", e)))?;

        let json = res
            .json::<serde_json::Value>()
            .await
            .map_err(|e| AppError::Internal(e.to_string()))?;

        let text = json
            .get("message")
            .and_then(|m| m.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or("No response content from local model.");

        return Ok(text.to_string());
    }

    let key = api_key.ok_or_else(|| AppError::BadRequest(format!("No key configured for {}", provider)))?;

    match provider {
        "groq" | "openai" => {
            let url = if provider == "groq" {
                "https://api.groq.com/openai/v1/chat/completions"
            } else {
                "https://api.openai.com/v1/chat/completions"
            };

            let res = client
                .post(url)
                .header("Authorization", format!("Bearer {}", key))
                .json(&serde_json::json!({
                    "model": model_id,
                    "messages": [
                        { "role": "system", "content": &system_prompt },
                        { "role": "user", "content": user_message }
                    ]
                }))
                .send()
                .await
                .map_err(|e| AppError::ServiceUnavailable(format!("API error: {}", e)))?;

            let json = res
                .json::<serde_json::Value>()
                .await
                .map_err(|e| AppError::Internal(e.to_string()))?;

            let text = json
                .get("choices")
                .and_then(|c| c.get(0))
                .and_then(|ch| ch.get("message"))
                .and_then(|m| m.get("content"))
                .and_then(|s| s.as_str())
                .unwrap_or("No response received.");

            Ok(text.to_string())
        }
        "anthropic" => {
            let res = client
                .post("https://api.anthropic.com/v1/messages")
                .header("x-api-key", key)
                .header("anthropic-version", "2023-06-01")
                .json(&serde_json::json!({
                    "model": model_id,
                    "max_tokens": 4096,
                    "system": &system_prompt,
                    "messages": [
                        { "role": "user", "content": user_message }
                    ]
                }))
                .send()
                .await
                .map_err(|e| AppError::ServiceUnavailable(format!("Anthropic API error: {}", e)))?;

            let json = res
                .json::<serde_json::Value>()
                .await
                .map_err(|e| AppError::Internal(e.to_string()))?;

            let text = json
                .get("content")
                .and_then(|c| c.get(0))
                .and_then(|b| b.get("text"))
                .and_then(|s| s.as_str())
                .unwrap_or("No response received.");

            Ok(text.to_string())
        }
        "gemini" => {
            let url = format!(
                "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}",
                model_id, key
            );

            let res = client
                .post(url)
                .json(&serde_json::json!({
                    "systemInstruction": {
                        "parts": [
                            { "text": &system_prompt }
                        ]
                    },
                    "contents": [
                        {
                            "parts": [
                                { "text": user_message }
                            ]
                        }
                    ]
                }))
                .send()
                .await
                .map_err(|e| AppError::ServiceUnavailable(format!("Gemini API error: {}", e)))?;

            let json = res
                .json::<serde_json::Value>()
                .await
                .map_err(|e| AppError::Internal(e.to_string()))?;

            let text = json
                .get("candidates")
                .and_then(|c| c.get(0))
                .and_then(|cand| cand.get("content"))
                .and_then(|cnt| cnt.get("parts"))
                .and_then(|p| p.get(0))
                .and_then(|pt| pt.get("text"))
                .and_then(|s| s.as_str())
                .unwrap_or("No response received.");

            Ok(text.to_string())
        }
        _ => Err(AppError::BadRequest(format!("Unsupported provider: {}", provider))),
    }
}

pub async fn run_turn(
    State((pool, config)): State<(DbPool, Config)>,
    Json(payload): Json<OrchestratorRequest>,
) -> Result<Json<OrchestratorResponse>, AppError> {
    let api_key = if payload.provider != "ollama" {
        get_decrypted_key(&pool, &payload.provider).await
    } else {
        None
    };

    let session_id = if let Some(sid) = payload.session_id {
        sid
    } else {
        let (new_id,): (i32,) = sqlx::query_as(
            r#"
            INSERT INTO sessions (session_name, is_active)
            VALUES ($1, true)
            RETURNING session_id
            "#,
        )
        .bind("New chat")
        .fetch_one(&pool)
        .await?;
        new_id
    };

    // Save user chat message
    let _ = sqlx::query(
        r#"
        INSERT INTO chats (session_id, role, chat)
        VALUES ($1, 'user', $2)
        "#,
    )
    .bind(session_id)
    .bind(&payload.message)
    .execute(&pool)
    .await;

    let response_text = execute_llm_call(
        &config,
        &payload.provider,
        api_key.as_deref(),
        &payload.model_id,
        &payload.message,
    )
    .await?;

    // Save assistant chat message
    let _ = sqlx::query(
        r#"
        INSERT INTO chats (session_id, role, chat)
        VALUES ($1, 'assistant', $2)
        "#,
    )
    .bind(session_id)
    .bind(&response_text)
    .execute(&pool)
    .await;

    Ok(Json(OrchestratorResponse {
        provider: payload.provider,
        model_id: payload.model_id,
        session_id: Some(session_id),
        mode: "general".to_string(),
        modes: vec!["general".to_string()],
        summary: None,
        agents: serde_json::json!([]),
        thinking: None,
        content: Some(response_text),
        raw_xml: None,
        disk_report: None,
        process_report: None,
        network_report: None,
        commands_run: serde_json::json!([]),
    }))
}

pub async fn orchestrator_ws_handler(
    ws: WebSocketUpgrade,
    State((pool, config)): State<(DbPool, Config)>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_orchestrator_ws(socket, pool, config))
}

async fn handle_orchestrator_ws(mut socket: WebSocket, pool: DbPool, config: Config) {
    while let Some(Ok(msg)) = socket.next().await {
        if let Message::Text(text) = msg {
            if let Ok(req) = serde_json::from_str::<OrchestratorRequest>(&text) {
                let api_key = if req.provider != "ollama" {
                    get_decrypted_key(&pool, &req.provider).await
                } else {
                    None
                };

                let session_id = if let Some(sid) = req.session_id {
                    sid
                } else {
                    let new_id: Option<(i32,)> = sqlx::query_as(
                        r#"
                        INSERT INTO sessions (session_name, is_active)
                        VALUES ($1, true)
                        RETURNING session_id
                        "#,
                    )
                    .bind("New chat")
                    .fetch_optional(&pool)
                    .await
                    .ok()
                    .flatten();

                    let sid = new_id.map(|(i,)| i).unwrap_or(1);
                    let _ = socket
                        .send(Message::Text(
                            serde_json::to_string(&serde_json::json!({
                                "type": "session_created",
                                "session_id": sid,
                                "session_name": "New chat"
                            }))
                            .unwrap(),
                        ))
                        .await;
                    sid
                };

                let _ = socket
                    .send(Message::Text(
                        serde_json::to_string(&serde_json::json!({
                            "type": "started",
                            "session_id": session_id
                        }))
                        .unwrap(),
                    ))
                    .await;

                let _ = socket
                    .send(Message::Text(
                        serde_json::to_string(&serde_json::json!({
                            "type": "classified",
                            "mode": "general",
                            "modes": ["general"]
                        }))
                        .unwrap(),
                    ))
                    .await;

                let _ = socket
                    .send(Message::Text(
                        serde_json::to_string(&serde_json::json!({
                            "type": "agent_started",
                            "mode": "general"
                        }))
                        .unwrap(),
                    ))
                    .await;

                let _ = sqlx::query(
                    r#"
                    INSERT INTO chats (session_id, role, chat)
                    VALUES ($1, 'user', $2)
                    "#,
                )
                .bind(session_id)
                .bind(&req.message)
                .execute(&pool)
                .await;

                match execute_llm_call(
                    &config,
                    &req.provider,
                    api_key.as_deref(),
                    &req.model_id,
                    &req.message,
                )
                .await
                {
                    Ok(resp) => {
                        let _ = socket
                            .send(Message::Text(
                                serde_json::to_string(&serde_json::json!({
                                    "type": "delta",
                                    "content": resp
                                }))
                                .unwrap(),
                            ))
                            .await;

                        let _ = sqlx::query(
                            r#"
                            INSERT INTO chats (session_id, role, chat)
                            VALUES ($1, 'assistant', $2)
                            "#,
                        )
                        .bind(session_id)
                        .bind(&resp)
                        .execute(&pool)
                        .await;

                        let _ = socket
                            .send(Message::Text(
                                serde_json::to_string(&serde_json::json!({
                                    "type": "final",
                                    "session_id": session_id,
                                    "mode": "general",
                                    "modes": ["general"],
                                    "content": resp,
                                    "commands_run": []
                                }))
                                .unwrap(),
                            ))
                            .await;
                    }
                    Err(e) => {
                        let _ = socket
                            .send(Message::Text(
                                serde_json::to_string(&serde_json::json!({
                                    "type": "error",
                                    "detail": format!("{:?}", e)
                                }))
                                .unwrap(),
                            ))
                            .await;
                    }
                }
            }
        }
    }
}
