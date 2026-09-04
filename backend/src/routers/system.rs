use axum::Json;
use serde_json::{json, Value};
use std::time::Duration;
use tokio::time::sleep;

pub async fn shutdown() -> Json<Value> {
    tokio::spawn(async {
        sleep(Duration::from_millis(500)).await;
        std::process::exit(0);
    });
    Json(json!({ "message": "Server shutting down" }))
}
