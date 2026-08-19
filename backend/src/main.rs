use axum::{routing::get, Router};
use std::fs::File;
use std::net::SocketAddr;
use tower_http::cors::{Any, CorsLayer};
use tracing::{info, Level};
use tracing_subscriber::FmtSubscriber;

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

    // Build our application with routes
    let app = Router::new()
        .route("/health", get(health_handler))
        .route("/onboard", get(onboard_handler))
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
