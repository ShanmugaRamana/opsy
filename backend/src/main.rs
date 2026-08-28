use axum::{routing::{get, post}, Json, Router};
use axum::response::sse::{Event, KeepAlive, Sse};
use tokio_stream::wrappers::ReceiverStream;
use futures::StreamExt;
use std::convert::Infallible;
use std::sync::Arc;
use tokio::sync::Mutex;
use axum::extract::{State, Query};
use std::fs::File;
use std::net::SocketAddr;
use tower_http::cors::{Any, CorsLayer};
use tracing::{info, Level, error};
use tracing_subscriber::FmtSubscriber;

mod system;
mod onboard;

#[tokio::main]
async fn main() {
    // Open log file in append mode
    let file = File::options()
        .create(true)
        .append(true)
        .open("opsy-backend.log")
        .unwrap();

    // Set up tracing to write to opsy-backend.log
    let subscriber = FmtSubscriber::builder()
        .with_max_level(Level::INFO)
        .with_writer(move || file.try_clone().unwrap())
        .finish();

    tracing::subscriber::set_global_default(subscriber)
        .expect("setting default subscriber failed");

    // Configure CORS
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    // Share active process state across threads
    let state: onboard::ActiveProcess = Arc::new(Mutex::new(None));

    // Build our application with routes
    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/onboard", get(onboard_handler))
        .route("/onboard/specs", get(specs_handler))
        .route("/onboard/status", get(status_handler))
        .route("/onboard/submit", post(submit_handler))
        .route("/onboard/api-key", post(api_key_handler))
        .route("/onboard/run-model-stream", get(run_model_stream_handler))
        .route("/onboard/cancel-run", post(cancel_run_handler))
        .with_state(state)
        .layer(cors);

    // Run our app, listening on port 8000
    let addr = SocketAddr::from(([0, 0, 0, 0], 8000));
    info!("Server starting up on {}", addr);
    println!("Server running on http://{}", addr);
    
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn health_handler() -> &'static str {
    info!("GET /health requested");
    "OK"
}

async fn onboard_handler() -> &'static str {
    info!("GET /onboard requested");
    "Welcome to Opsy!"
}

async fn specs_handler() -> Json<system::types::SystemSpecs> {
    info!("GET /onboard/specs requested");
    Json(system::get_system_specs())
}

async fn status_handler() -> Json<onboard::types::UserData> {
    info!("GET /onboard/status requested");
    let mut user_data = onboard::read_user_data();
    if user_data.onboarded && user_data.suggestions.is_empty() {
        if let Some(ref specs) = user_data.system_specs {
            user_data.suggestions = onboard::get_recommendations(specs);
        }
    }
    Json(user_data)
}

async fn submit_handler() -> Result<Json<onboard::types::UserData>, (axum::http::StatusCode, String)> {
    // Automatically retrieve system username
    let username = std::env::var("USER")
        .or_else(|_| std::env::var("USERNAME"))
        .unwrap_or_else(|_| "User".to_string());

    info!("POST /onboard/submit requested. Onboarding system user: {}", username);
    
    // Scan system specifications using system module
    let specs = system::get_system_specs();
    info!("System specifications scanned: CPU={}, RAM={}GB, Disk={}GB, GPUs={}", 
        specs.cpu.model_name, specs.ram.total_gb, specs.disk.total_gb, specs.gpus.len());

    let suggestions = onboard::get_recommendations(&specs);

    let user_data = onboard::types::UserData {
        onboarded: true,
        username,
        system_specs: Some(specs),
        suggestions,
        api_key: None,
        active_model: None,
    };

    // Save to file
    if let Err(e) = onboard::write_user_data(&user_data) {
        error!("Failed to write user_data.json: {}", e);
        return Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, e.to_string()));
    }

    info!("User onboarding data successfully saved to user_data.json");
    Ok(Json(user_data))
}

#[derive(serde::Deserialize)]
struct ApiKeyRequest {
    provider: String,
    key: String,
}

async fn api_key_handler(
    Json(payload): Json<ApiKeyRequest>,
) -> Result<Json<onboard::types::UserData>, (axum::http::StatusCode, String)> {
    info!("POST /onboard/api-key requested for provider: {}", payload.provider);
    match onboard::save_provider_api_key(payload.provider, payload.key) {
        Ok(data) => Ok(Json(data)),
        Err(e) => {
            error!("Failed to save api key: {}", e);
            Err((axum::http::StatusCode::INTERNAL_SERVER_ERROR, e))
        }
    }
}

async fn run_model_stream_handler(
    State(active_proc): State<onboard::ActiveProcess>,
    Query(params): Query<std::collections::HashMap<String, String>>,
) -> Sse<impl futures::Stream<Item = Result<Event, Infallible>>> {
    let model_name = params.get("model").cloned().unwrap_or_else(|| "llama3.2:3b".to_string());
    info!("GET /onboard/run-model-stream requested for model: {}", model_name);

    let (tx, rx) = tokio::sync::mpsc::channel(100);
    
    // Spawn the installation and pull process in the background
    tokio::spawn(onboard::run_install_and_pull(model_name, tx, active_proc));

    // Convert our receiver into a stream of Event objects
    let stream = ReceiverStream::new(rx).map(|event| {
        let json = serde_json::to_string(&event).unwrap_or_default();
        Ok(Event::default().data(json))
    });

    Sse::new(stream).keep_alive(KeepAlive::default())
}

async fn cancel_run_handler(
    State(active_proc): State<onboard::ActiveProcess>,
) -> Result<&'static str, (axum::http::StatusCode, String)> {
    info!("POST /onboard/cancel-run requested");
    match onboard::cancel_active_process(active_proc).await {
        Ok(_) => Ok("Cancelled successfully"),
        Err(e) => {
            error!("Failed to cancel process: {}", e);
            Err((axum::http::StatusCode::BAD_REQUEST, e))
        }
    }
}
