use axum::routing::{get, post};
use axum::Router;
use std::fs::File;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::Mutex;
use tower_http::cors::{Any, CorsLayer};
use tracing::{info, Level};
use tracing_subscriber::FmtSubscriber;

mod shared;
mod system;
mod onboard;

use shared::bus::{CommandBus, QueryBus};

#[derive(Clone)]
pub struct AppState {
    pub command_bus: CommandBus,
    pub query_bus: QueryBus,
    pub active_proc: onboard::ActiveProcess,
}

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

    // Build QueryBus and CommandBus
    let query_bus_builder = QueryBus::builder();
    let query_bus_builder = system::register_queries(query_bus_builder);
    let query_bus_builder = onboard::register_queries(query_bus_builder);
    let query_bus = query_bus_builder.build();

    let command_bus_builder = CommandBus::builder();
    let command_bus_builder = onboard::register_commands(command_bus_builder);
    let command_bus = command_bus_builder.build();

    let active_proc: onboard::ActiveProcess = Arc::new(Mutex::new(None));

    let onboard_state = onboard::http::OnboardState {
        command_bus: command_bus.clone(),
        query_bus: query_bus.clone(),
        active_proc: active_proc.clone(),
    };

    // Build our application with routes
    let system_router = Router::new()
        .route("/onboard/specs", get(system::http::specs_handler))
        .with_state(query_bus);

    let onboard_router = Router::new()
        .route("/onboard", get(onboard::http::onboard_handler))
        .route("/onboard/status", get(onboard::http::status_handler))
        .route("/onboard/submit", post(onboard::http::submit_handler))
        .route("/onboard/api-key", post(onboard::http::api_key_handler))
        .route("/onboard/run-model-stream", get(onboard::http::run_model_stream_handler))
        .route("/onboard/cancel-run", post(onboard::http::cancel_run_handler))
        .with_state(onboard_state);

    let app = Router::new()
        .route("/health", get(health_handler))
        .merge(system_router)
        .merge(onboard_router)
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
