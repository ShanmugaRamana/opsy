use std::collections::HashMap;
use std::convert::Infallible;
use axum::extract::{Query, State};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::Json;
use futures::StreamExt;
use serde::Deserialize;
use tokio_stream::wrappers::ReceiverStream;
use tracing::info;

use crate::onboard::commands::{CancelRunCommand, PullModelCommand, SaveApiKeyCommand, SaveProfileCommand};
use crate::onboard::domain::UserData;
use crate::onboard::infra::runner::ActiveProcess;
use crate::onboard::queries::{GetProfileQuery, GetRecommendationsQuery};
use crate::shared::bus::{CommandBus, QueryBus};
use crate::shared::error::AppError;
use crate::system::queries::GetSystemSpecsQuery;

#[derive(Clone)]
pub struct OnboardState {
    pub command_bus: CommandBus,
    pub query_bus: QueryBus,
    pub active_proc: ActiveProcess,
}

pub async fn onboard_handler() -> &'static str {
    info!("GET /onboard requested");
    "Welcome to Opsy!"
}

pub async fn status_handler(
    State(state): State<OnboardState>,
) -> Result<Json<UserData>, AppError> {
    info!("GET /onboard/status requested");
    let mut user_data = state.query_bus.dispatch(GetProfileQuery).await?;
    if user_data.onboarded && user_data.suggestions.is_empty() {
        if let Some(ref specs) = user_data.system_specs {
            let suggestions = state
                .query_bus
                .dispatch(GetRecommendationsQuery {
                    specs: specs.clone(),
                })
                .await?;
            user_data.suggestions = suggestions;
        }
    }
    Ok(Json(user_data))
}

pub async fn submit_handler(
    State(state): State<OnboardState>,
) -> Result<Json<UserData>, AppError> {
    let username = std::env::var("USER")
        .or_else(|_| std::env::var("USERNAME"))
        .unwrap_or_else(|_| "User".to_string());

    info!("POST /onboard/submit requested. Onboarding system user: {}", username);

    let specs = state.query_bus.dispatch(GetSystemSpecsQuery).await?;
    info!(
        "System specifications scanned: CPU={}, RAM={}GB, Disk={}GB, GPUs={}",
        specs.cpu.model_name, specs.ram.total_gb, specs.disk.total_gb, specs.gpus.len()
    );

    let suggestions = state
        .query_bus
        .dispatch(GetRecommendationsQuery {
            specs: specs.clone(),
        })
        .await?;

    let user_data = UserData {
        onboarded: true,
        username,
        system_specs: Some(specs),
        suggestions,
        api_key: None,
        active_model: None,
    };

    let saved = state
        .command_bus
        .dispatch(SaveProfileCommand { profile: user_data })
        .await?;

    info!("User onboarding data successfully saved to user_data.json");
    Ok(Json(saved))
}

#[derive(Deserialize)]
pub struct ApiKeyRequest {
    pub provider: String,
    pub key: String,
}

pub async fn api_key_handler(
    State(state): State<OnboardState>,
    Json(payload): Json<ApiKeyRequest>,
) -> Result<Json<UserData>, AppError> {
    info!("POST /onboard/api-key requested for provider: {}", payload.provider);
    let updated = state
        .command_bus
        .dispatch(SaveApiKeyCommand {
            provider: payload.provider,
            key: payload.key,
        })
        .await?;
    Ok(Json(updated))
}

pub async fn run_model_stream_handler(
    State(state): State<OnboardState>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Sse<impl futures::Stream<Item = Result<Event, Infallible>>>, AppError> {
    let model_name = params.get("model").cloned().unwrap_or_else(|| "llama3.2:3b".to_string());
    info!("GET /onboard/run-model-stream requested for model: {}", model_name);

    let rx = state
        .command_bus
        .dispatch(PullModelCommand {
            model_name,
            active_proc: state.active_proc.clone(),
        })
        .await?;

    let stream = ReceiverStream::new(rx).map(|event| {
        let json = serde_json::to_string(&event).unwrap_or_default();
        Ok(Event::default().data(json))
    });

    Ok(Sse::new(stream).keep_alive(KeepAlive::default()))
}

pub async fn cancel_run_handler(
    State(state): State<OnboardState>,
) -> Result<&'static str, AppError> {
    info!("POST /onboard/cancel-run requested");
    state
        .command_bus
        .dispatch(CancelRunCommand {
            active_proc: state.active_proc.clone(),
        })
        .await?;
    Ok("Cancelled successfully")
}
