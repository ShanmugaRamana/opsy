use axum::Json;
use serde_json::{json, Value};

pub async fn root() -> Json<Value> {
    Json(json!({ "message": "success" }))
}
