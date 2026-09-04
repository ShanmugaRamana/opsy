use axum::extract::State;
use axum::Json;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::Row;

use crate::db::DbPool;
use crate::error::AppError;

#[derive(Serialize)]
pub struct VerifyResponse {
    pub onboarding_required: bool,
    pub setup_required: bool,
}

#[derive(Deserialize)]
pub struct OnboardingUserPayload {
    pub name: String,
    pub profile_pic: String,
    pub linux_experience: String,
    pub role_use_case: String,
}

pub async fn verify_onboarding(State(pool): State<DbPool>) -> Result<Json<VerifyResponse>, AppError> {
    let user_count: (i64,) = sqlx::query_as(r#"SELECT COUNT(*) FROM "user""#)
        .fetch_one(&pool)
        .await
        .unwrap_or((0,));

    let onboarding_required = user_count.0 == 0;

    let has_byok: bool = if !onboarding_required {
        let (count,): (i64,) = sqlx::query_as(r#"SELECT COUNT(*) FROM byok"#)
            .fetch_one(&pool)
            .await
            .unwrap_or((0,));
        count > 0
    } else {
        false
    };

    let has_local_ready: bool = if !onboarding_required && !has_byok {
        let (count,): (i64,) = sqlx::query_as(r#"SELECT COUNT(*) FROM local_models WHERE status = 'ready'"#)
            .fetch_one(&pool)
            .await
            .unwrap_or((0,));
        count > 0
    } else {
        false
    };

    let setup_required = if onboarding_required {
        false
    } else {
        !(has_byok || has_local_ready)
    };

    Ok(Json(VerifyResponse {
        onboarding_required,
        setup_required,
    }))
}

pub async fn create_onboarding_user(
    State(pool): State<DbPool>,
    Json(payload): Json<OnboardingUserPayload>,
) -> Result<Json<Value>, AppError> {
    if payload.name.trim().is_empty() {
        return Err(AppError::BadRequest("Name cannot be empty".to_string()));
    }

    sqlx::query(
        r#"
        INSERT INTO "user" (name, profile_pic, linux_experience, role_use_case)
        VALUES ($1, $2, $3, $4)
        "#,
    )
    .bind(payload.name)
    .bind(payload.profile_pic)
    .bind(payload.linux_experience)
    .bind(payload.role_use_case)
    .execute(&pool)
    .await?;

    Ok(Json(json!({ "message": "success" })))
}
