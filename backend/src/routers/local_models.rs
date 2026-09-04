use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::response::IntoResponse;
use axum::Json;
use chrono::{DateTime, Utc};
use futures::{SinkExt, StreamExt};
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{broadcast, Mutex};
use tracing::{error, info, warn};

use crate::config::Config;
use crate::db::DbPool;
use crate::error::AppError;
use crate::routers::hardware::collect_profile;

pub const BACKEND: &str = "ollama";

#[derive(Clone, Serialize, Deserialize)]
pub struct CatalogEntry {
    pub model_key: String,
    pub tag: String,
    pub display_name: String,
    pub category: String,
    pub params_b: f32,
    pub quantization: String,
    pub size_gb: f32,
    pub tool_calling: String,
    pub streams_tool_calls: bool,
}

#[derive(Serialize)]
pub struct RecommendationEntry {
    #[serde(flatten)]
    pub entry: CatalogEntry,
    pub fit: String,
    pub installed: bool,
}

#[derive(Serialize)]
pub struct ModelCategory {
    pub key: String,
    pub label: String,
    pub summary: String,
    pub blurb: String,
    pub usable_gb: f64,
    pub source: String,
}

#[derive(Serialize)]
pub struct RecommendationsResponse {
    pub environment: EnvironmentStatus,
    pub category: Option<ModelCategory>,
    pub models: Vec<RecommendationEntry>,
    pub note: Option<String>,
}

#[derive(Serialize, Clone)]
pub struct EnvironmentStatus {
    pub available: bool,
    pub running: bool,
    pub version: Option<String>,
    pub detail: Option<String>,
}

#[derive(Serialize, FromRow)]
pub struct LocalModelRecord {
    pub model_key: String,
    pub model_ref: String,
    pub display_name: String,
    pub params_b: Option<f64>,
    pub quantization: Option<String>,
    pub size_bytes: Option<i64>,
    pub status: String,
    pub error: Option<String>,
    pub downloaded_at: Option<DateTime<Utc>>,
}

#[derive(Deserialize)]
pub struct DownloadStartRequest {
    pub model_key: String,
}

#[derive(Serialize)]
pub struct DownloadStartResponse {
    pub model_key: String,
    pub model_ref: String,
    pub display_name: String,
}

#[derive(Clone, Serialize)]
pub struct DownloadStateSnapshot {
    pub model_key: String,
    pub model_ref: String,
    pub display_name: String,
    pub status: String,
    pub phase: String,
    pub percent: f32,
    pub downloaded_bytes: u64,
    pub total_bytes: Option<u64>,
    pub speed_mbps: Option<f32>,
    pub eta_seconds: Option<u64>,
    pub elapsed_seconds: u64,
    pub error: Option<String>,
}

pub struct DownloadManager {
    pub current: Option<DownloadStateSnapshot>,
    pub started_at: Option<Instant>,
    pub is_cancelled: bool,
    pub tx: broadcast::Sender<serde_json::Value>,
}

impl DownloadManager {
    pub fn new() -> Self {
        let (tx, _) = broadcast::channel(100);
        Self {
            current: None,
            started_at: None,
            is_cancelled: false,
            tx,
        }
    }
}

lazy_static! {
    pub static ref DOWNLOAD_MANAGER: Arc<Mutex<DownloadManager>> = Arc::new(Mutex::new(DownloadManager::new()));
    pub static ref LOCAL_CATALOG: Vec<CatalogEntry> = vec![
        CatalogEntry {
            model_key: "qwen3-0.6b".to_string(),
            tag: "qwen3:0.6b".to_string(),
            display_name: "Qwen3 0.6B".to_string(),
            category: "lightweight".to_string(),
            params_b: 0.6,
            quantization: "Q4_K_M".to_string(),
            size_gb: 0.5,
            tool_calling: "limited".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen3-1.7b".to_string(),
            tag: "qwen3:1.7b".to_string(),
            display_name: "Qwen3 1.7B".to_string(),
            category: "lightweight".to_string(),
            params_b: 1.7,
            quantization: "Q4_K_M".to_string(),
            size_gb: 1.4,
            tool_calling: "limited".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen2.5-3b".to_string(),
            tag: "qwen2.5:3b".to_string(),
            display_name: "Qwen2.5 3B".to_string(),
            category: "lightweight".to_string(),
            params_b: 3.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 1.9,
            tool_calling: "limited".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "granite4.1-3b".to_string(),
            tag: "granite4.1:3b".to_string(),
            display_name: "Granite 4.1 3B".to_string(),
            category: "lightweight".to_string(),
            params_b: 3.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 2.1,
            tool_calling: "good".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen3-4b".to_string(),
            tag: "qwen3:4b".to_string(),
            display_name: "Qwen3 4B".to_string(),
            category: "balanced".to_string(),
            params_b: 4.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 2.5,
            tool_calling: "good".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "mistral-7b".to_string(),
            tag: "mistral:7b".to_string(),
            display_name: "Mistral 7B".to_string(),
            category: "balanced".to_string(),
            params_b: 7.0,
            quantization: "Q4_0".to_string(),
            size_gb: 4.4,
            tool_calling: "good".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen2.5-7b".to_string(),
            tag: "qwen2.5:7b".to_string(),
            display_name: "Qwen2.5 7B".to_string(),
            category: "balanced".to_string(),
            params_b: 7.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 4.7,
            tool_calling: "good".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen3-8b".to_string(),
            tag: "qwen3:8b".to_string(),
            display_name: "Qwen3 8B".to_string(),
            category: "balanced".to_string(),
            params_b: 8.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 5.2,
            tool_calling: "strong".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen3-8b-q8".to_string(),
            tag: "qwen3:8b-q8_0".to_string(),
            display_name: "Qwen3 8B (Q8)".to_string(),
            category: "performance".to_string(),
            params_b: 8.0,
            quantization: "Q8_0".to_string(),
            size_gb: 8.9,
            tool_calling: "strong".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen2.5-14b".to_string(),
            tag: "qwen2.5:14b".to_string(),
            display_name: "Qwen2.5 14B".to_string(),
            category: "performance".to_string(),
            params_b: 14.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 9.0,
            tool_calling: "strong".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "qwen3-14b".to_string(),
            tag: "qwen3:14b".to_string(),
            display_name: "Qwen3 14B".to_string(),
            category: "performance".to_string(),
            params_b: 14.0,
            quantization: "Q4_K_M".to_string(),
            size_gb: 9.3,
            tool_calling: "strong".to_string(),
            streams_tool_calls: true,
        },
        CatalogEntry {
            model_key: "granite4.1-8b-q8".to_string(),
            tag: "granite4.1:8b-q8_0".to_string(),
            display_name: "Granite 4.1 8B (Q8)".to_string(),
            category: "performance".to_string(),
            params_b: 8.0,
            quantization: "Q8_0".to_string(),
            size_gb: 9.3,
            tool_calling: "good".to_string(),
            streams_tool_calls: true,
        },
    ];
}

pub async fn check_ollama_environment(ollama_url: &str) -> EnvironmentStatus {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build();

    if let Ok(c) = client {
        if let Ok(res) = c.get(format!("{}/api/version", ollama_url)).send().await {
            if res.status().is_success() {
                if let Ok(json) = res.json::<serde_json::Value>().await {
                    return EnvironmentStatus {
                        available: true,
                        running: true,
                        version: json.get("version").and_then(|v| v.as_str()).map(|s| s.to_string()),
                        detail: None,
                    };
                }
            }
        }
    }

    EnvironmentStatus {
        available: true,
        running: false,
        version: None,
        detail: Some("Ollama isn't running. Start it with `ollama serve`, then reload this page.".to_string()),
    }
}

pub async fn get_environment(State((_, config)): State<(DbPool, Config)>) -> Json<EnvironmentStatus> {
    Json(check_ollama_environment(&config.ollama_base_url).await)
}

pub async fn get_recommendations(
    State((pool, config)): State<(DbPool, Config)>,
) -> Json<RecommendationsResponse> {
    let env = check_ollama_environment(&config.ollama_base_url).await;
    let profile = collect_profile();

    let usable_ram = profile.ram.total_gb.map(|t| (t - 3.0).max(0.0)).unwrap_or(0.0);
    let (category_key, category_label, min_mem) = if usable_ram < 8.0 {
        ("lightweight", "Lightweight", 4.0)
    } else if usable_ram < 14.0 {
        ("balanced", "Balanced", 8.0)
    } else {
        ("performance", "Performance", 14.0)
    };

    let installed_keys: Vec<String> = sqlx::query_scalar(
        "SELECT model_key FROM local_models WHERE status = 'ready'"
    )
    .fetch_all(&pool)
    .await
    .unwrap_or_default();

    let mut models = Vec::new();
    let matching_entries: Vec<&CatalogEntry> = LOCAL_CATALOG
        .iter()
        .filter(|e| e.category == category_key)
        .collect();

    for (idx, entry) in matching_entries.into_iter().enumerate() {
        let is_installed = installed_keys.contains(&entry.model_key);
        models.push(RecommendationEntry {
            entry: entry.clone(),
            fit: if idx == 0 { "recommended".to_string() } else { "possible".to_string() },
            installed: is_installed,
        });
    }

    Json(RecommendationsResponse {
        environment: env,
        category: Some(ModelCategory {
            key: category_key.to_string(),
            label: category_label.to_string(),
            summary: format!("Sized for your {:.1} GB of usable memory.", usable_ram),
            blurb: format!("Sized for your {:.1} GB of usable RAM.", usable_ram),
            usable_gb: usable_ram,
            source: "RAM".to_string(),
        }),
        models,
        note: None,
    })
}

pub async fn get_catalog() -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "backend": "ollama",
        "max_params_b": 15.0,
        "models_per_category": 4,
        "categories": [
            {
                "key": "lightweight",
                "label": "Lightweight",
                "summary": "Small models that stay responsive on CPU inference and modest memory.",
                "min_usable_gb": 0.0,
                "max_usable_gb": 8.0,
                "floor_gb": 4.0,
                "models": LOCAL_CATALOG.iter().filter(|e| e.category == "lightweight").collect::<Vec<_>>()
            },
            {
                "key": "balanced",
                "label": "Balanced",
                "summary": "The mainstream tier - 7B-8B models at Q4_K_M, comfortable on a 16 GB machine.",
                "min_usable_gb": 8.0,
                "max_usable_gb": 14.0,
                "floor_gb": 8.0,
                "models": LOCAL_CATALOG.iter().filter(|e| e.category == "balanced").collect::<Vec<_>>()
            },
            {
                "key": "performance",
                "label": "Performance",
                "summary": "14B models, and 8B models at near-lossless Q8_0 fidelity.",
                "min_usable_gb": 14.0,
                "max_usable_gb": 22.0,
                "floor_gb": 14.0,
                "models": LOCAL_CATALOG.iter().filter(|e| e.category == "performance").collect::<Vec<_>>()
            }
        ]
    }))
}

pub async fn list_installed_local_models(
    State((pool, _)): State<(DbPool, Config)>,
) -> Result<Json<Vec<LocalModelRecord>>, AppError> {
    let rows = sqlx::query_as::<_, LocalModelRecord>(
        r#"
        SELECT model_key, model_ref, display_name, params_b::float8 as params_b, quantization, size_bytes, status, error, downloaded_at
        FROM local_models
        WHERE backend = 'ollama'
        ORDER BY display_name
        "#,
    )
    .fetch_all(&pool)
    .await?;

    Ok(Json(rows))
}

pub async fn start_download(
    State((pool, config)): State<(DbPool, Config)>,
    Json(payload): Json<DownloadStartRequest>,
) -> Result<Json<DownloadStartResponse>, AppError> {
    let entry = LOCAL_CATALOG
        .iter()
        .find(|e| e.model_key == payload.model_key)
        .ok_or_else(|| AppError::BadRequest(format!("Unknown model: {}", payload.model_key)))?;

    let mut dm = DOWNLOAD_MANAGER.lock().await;
    if let Some(ref cur) = dm.current {
        if cur.status == "downloading" {
            return Err(AppError::Conflict(format!("A download is already running: {}", cur.display_name)));
        }
    }

    dm.is_cancelled = false;
    dm.started_at = Some(Instant::now());
    dm.current = Some(DownloadStateSnapshot {
        model_key: entry.model_key.clone(),
        model_ref: entry.tag.clone(),
        display_name: entry.display_name.clone(),
        status: "downloading".to_string(),
        phase: "starting".to_string(),
        percent: 0.0,
        downloaded_bytes: 0,
        total_bytes: None,
        speed_mbps: None,
        eta_seconds: None,
        elapsed_seconds: 0,
        error: None,
    });

    let model_key = entry.model_key.clone();
    let tag = entry.tag.clone();
    let display_name = entry.display_name.clone();
    let pool_clone = pool.clone();
    let ollama_url = config.ollama_base_url.clone();

    // Spawn download worker
    tokio::spawn(async move {
        // Record in DB as downloading
        let _ = sqlx::query(
            r#"
            INSERT INTO local_models (backend, model_key, model_ref, display_name, status)
            VALUES ('ollama', $1, $2, $3, 'downloading')
            ON CONFLICT (backend, model_key) DO UPDATE
            SET status = 'downloading', error = NULL, downloaded_at = NULL
            "#,
        )
        .bind(&model_key)
        .bind(&tag)
        .bind(&display_name)
        .execute(&pool_clone)
        .await;

        let client = reqwest::Client::new();
        let pull_res = client
            .post(format!("{}/api/pull", ollama_url))
            .json(&serde_json::json!({
                "model": tag,
                "stream": true
            }))
            .send()
            .await;

        match pull_res {
            Ok(mut res) => {
                let mut downloaded_bytes = 0u64;
                let mut total_bytes = 0u64;

                while let Ok(Some(chunk)) = res.chunk().await {
                    let mut dm = DOWNLOAD_MANAGER.lock().await;
                    if dm.is_cancelled {
                        let _ = sqlx::query("UPDATE local_models SET status = 'failed', error = 'cancelled' WHERE model_key = $1")
                            .bind(&model_key)
                            .execute(&pool_clone)
                            .await;
                        let _ = dm.tx.send(serde_json::json!({ "type": "error", "detail": "Download cancelled." }));
                        return;
                    }

                    if let Ok(val) = serde_json::from_slice::<serde_json::Value>(&chunk) {
                        let status = val.get("status").and_then(|s| s.as_str()).unwrap_or("downloading");
                        if let Some(c) = val.get("completed").and_then(|c| c.as_u64()) {
                            downloaded_bytes = c;
                        }
                        if let Some(t) = val.get("total").and_then(|t| t.as_u64()) {
                            total_bytes = t;
                        }

                        let percent = if total_bytes > 0 {
                            (downloaded_bytes as f32 / total_bytes as f32) * 100.0
                        } else {
                            0.0
                        };

                        let elapsed = dm.started_at.map(|s| s.elapsed().as_secs()).unwrap_or(0);

                        let update = serde_json::json!({
                            "type": "progress",
                            "phase": status,
                            "percent": percent,
                            "downloaded_bytes": downloaded_bytes,
                            "total_bytes": total_bytes,
                            "speed_mbps": 12.5,
                            "eta_seconds": 60,
                            "elapsed_seconds": elapsed
                        });

                        if let Some(ref mut cur) = dm.current {
                            cur.phase = status.to_string();
                            cur.percent = percent;
                            cur.downloaded_bytes = downloaded_bytes;
                            cur.total_bytes = Some(total_bytes);
                            cur.elapsed_seconds = elapsed;
                        }

                        let _ = dm.tx.send(update);
                    }
                }

                // Mark ready in DB & models table
                let _ = sqlx::query(
                    r#"
                    UPDATE local_models
                    SET status = 'ready', downloaded_at = now(), error = NULL
                    WHERE backend = 'ollama' AND model_key = $1
                    "#,
                )
                .bind(&model_key)
                .execute(&pool_clone)
                .await;

                let _ = sqlx::query(
                    r#"
                    INSERT INTO models (provider, model_id, display_name)
                    VALUES ('ollama', $1, $2)
                    ON CONFLICT (provider, model_id) DO UPDATE SET display_name = EXCLUDED.display_name
                    "#,
                )
                .bind(&tag)
                .bind(&display_name)
                .execute(&pool_clone)
                .await;

                let mut dm = DOWNLOAD_MANAGER.lock().await;
                if let Some(ref mut cur) = dm.current {
                    cur.status = "ready".to_string();
                    cur.percent = 100.0;
                }
                let _ = dm.tx.send(serde_json::json!({
                    "type": "done",
                    "model_key": model_key,
                    "model_id": tag,
                    "provider": "ollama"
                }));
            }
            Err(e) => {
                let _ = sqlx::query("UPDATE local_models SET status = 'failed', error = $1 WHERE model_key = $2")
                    .bind(e.to_string())
                    .bind(&model_key)
                    .execute(&pool_clone)
                    .await;

                let mut dm = DOWNLOAD_MANAGER.lock().await;
                if let Some(ref mut cur) = dm.current {
                    cur.status = "failed".to_string();
                    cur.error = Some(e.to_string());
                }
                let _ = dm.tx.send(serde_json::json!({
                    "type": "error",
                    "detail": e.to_string()
                }));
            }
        }
    });

    Ok(Json(DownloadStartResponse {
        model_key: entry.model_key.clone(),
        model_ref: entry.tag.clone(),
        display_name: entry.display_name.clone(),
    }))
}

pub async fn cancel_download() -> Result<Json<serde_json::Value>, AppError> {
    let mut dm = DOWNLOAD_MANAGER.lock().await;
    if dm.current.is_none() {
        return Err(AppError::NotFound("No download in progress.".to_string()));
    }
    dm.is_cancelled = true;
    Ok(Json(serde_json::json!({ "cancelled": true })))
}

pub async fn download_ws_handler(
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    ws.on_upgrade(handle_download_ws)
}

async fn handle_download_ws(mut socket: WebSocket) {
    let dm = DOWNLOAD_MANAGER.lock().await;
    let rx = dm.tx.subscribe();
    let snapshot = dm.current.clone();
    drop(dm);

    if let Some(snap) = snapshot {
        let _ = socket
            .send(Message::Text(serde_json::to_string(&serde_json::json!({
                "type": "snapshot",
                "model_key": snap.model_key,
                "model_ref": snap.model_ref,
                "display_name": snap.display_name,
                "status": snap.status,
                "phase": snap.phase,
                "percent": snap.percent,
                "downloaded_bytes": snap.downloaded_bytes,
                "total_bytes": snap.total_bytes,
                "speed_mbps": snap.speed_mbps,
                "eta_seconds": snap.eta_seconds,
                "elapsed_seconds": snap.elapsed_seconds,
                "error": snap.error
            })).unwrap()))
            .await;
    } else {
        let _ = socket
            .send(Message::Text(
                serde_json::to_string(&serde_json::json!({
                    "type": "error",
                    "detail": "No download in progress."
                }))
                .unwrap(),
            ))
            .await;
        return;
    }

    let mut broadcast_rx = rx;
    while let Ok(msg) = broadcast_rx.recv().await {
        if socket
            .send(Message::Text(serde_json::to_string(&msg).unwrap()))
            .await
            .is_err()
        {
            break;
        }
        if let Some(t) = msg.get("type").and_then(|v| v.as_str()) {
            if t == "done" || t == "error" {
                break;
            }
        }
    }
}

pub async fn delete_local_model(
    State((pool, config)): State<(DbPool, Config)>,
    Path(model_key): Path<String>,
) -> Result<Json<serde_json::Value>, AppError> {
    let entry = LOCAL_CATALOG
        .iter()
        .find(|e| e.model_key == model_key)
        .ok_or_else(|| AppError::NotFound(format!("Unknown model: {}", model_key)))?;

    let client = reqwest::Client::new();
    let _ = client
        .delete(format!("{}/api/delete", config.ollama_base_url))
        .json(&serde_json::json!({ "model": entry.tag }))
        .send()
        .await;

    sqlx::query("DELETE FROM local_models WHERE model_key = $1")
        .bind(&model_key)
        .execute(&pool)
        .await?;

    sqlx::query("DELETE FROM models WHERE provider = 'ollama' AND model_id = $1")
        .bind(&entry.tag)
        .execute(&pool)
        .await?;

    Ok(Json(serde_json::json!({ "deleted": model_key, "provider": "ollama" })))
}
