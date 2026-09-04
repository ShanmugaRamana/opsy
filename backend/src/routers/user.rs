use axum::extract::State;
use axum::Json;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

use crate::db::DbPool;
use crate::error::AppError;

#[derive(Serialize, FromRow)]
pub struct UserRecord {
    pub id: i32,
    pub name: String,
    pub profile_pic: String,
    pub linux_experience: String,
    pub role_use_case: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Serialize, Deserialize, FromRow)]
pub struct PreferencesRecord {
    pub always_approve_commands: bool,
}

#[derive(Deserialize)]
pub struct PreferencesUpdate {
    pub always_approve_commands: bool,
}

pub async fn list_all_users(State(pool): State<DbPool>) -> Result<Json<Vec<UserRecord>>, AppError> {
    let users = sqlx::query_as::<_, UserRecord>(
        r#"
        SELECT id, name, profile_pic, linux_experience, role_use_case, created_at
        FROM "user"
        ORDER BY id
        "#,
    )
    .fetch_all(&pool)
    .await?;

    Ok(Json(users))
}

pub async fn read_preferences(State(pool): State<DbPool>) -> Result<Json<PreferencesRecord>, AppError> {
    let pref = sqlx::query_as::<_, PreferencesRecord>(
        r#"
        SELECT always_approve_commands
        FROM "user"
        ORDER BY id
        LIMIT 1
        "#,
    )
    .fetch_optional(&pool)
    .await?;

    match pref {
        Some(p) => Ok(Json(p)),
        None => Err(AppError::NotFound("No user has been onboarded yet.".to_string())),
    }
}

pub async fn update_preferences(
    State(pool): State<DbPool>,
    Json(payload): Json<PreferencesUpdate>,
) -> Result<Json<PreferencesRecord>, AppError> {
    let pref = sqlx::query_as::<_, PreferencesRecord>(
        r#"
        UPDATE "user"
        SET always_approve_commands = $1
        WHERE id = (SELECT id FROM "user" ORDER BY id LIMIT 1)
        RETURNING always_approve_commands
        "#,
    )
    .bind(payload.always_approve_commands)
    .fetch_optional(&pool)
    .await?;

    match pref {
        Some(p) => Ok(Json(p)),
        None => Err(AppError::NotFound("No user has been onboarded yet.".to_string())),
    }
}
