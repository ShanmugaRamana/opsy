use sqlx::postgres::PgPoolOptions;
use sqlx::{Pool, Postgres};
use std::time::Duration;
use tracing::{info, warn};

pub type DbPool = Pool<Postgres>;

pub async fn create_pool(database_url: &str) -> Result<DbPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(10)
        .acquire_timeout(Duration::from_secs(3))
        .connect(database_url)
        .await
}

pub async fn init_db(pool: &DbPool) -> Result<(), sqlx::Error> {
    info!("Running database schema migrations if needed...");

    // Create user table
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS "user" (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            profile_pic TEXT NOT NULL,
            linux_experience TEXT NOT NULL,
            role_use_case TEXT NOT NULL,
            always_approve_commands BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        "#,
    )
    .execute(pool)
    .await?;

    // Ensure always_approve_commands column exists in case older DB schema
    let _ = sqlx::query(
        r#"
        ALTER TABLE "user" ADD COLUMN IF NOT EXISTS always_approve_commands BOOLEAN NOT NULL DEFAULT false;
        "#,
    )
    .execute(pool)
    .await;

    // Create byok table
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS byok (
            id SERIAL PRIMARY KEY,
            provider TEXT NOT NULL UNIQUE,
            api_key_encrypted TEXT NOT NULL,
            key_last4 TEXT NOT NULL,
            verified_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        "#,
    )
    .execute(pool)
    .await?;

    // Create models table
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS models (
            id SERIAL PRIMARY KEY,
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (provider, model_id)
        );
        "#,
    )
    .execute(pool)
    .await?;

    // Create local_models table
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS local_models (
            id SERIAL PRIMARY KEY,
            backend TEXT NOT NULL DEFAULT 'ollama',
            model_key TEXT NOT NULL,
            model_ref TEXT NOT NULL,
            display_name TEXT NOT NULL,
            params_b NUMERIC(5,2),
            quantization TEXT,
            size_bytes BIGINT,
            context_length INTEGER NOT NULL,
            supports_tools BOOLEAN NOT NULL DEFAULT TRUE,
            status TEXT NOT NULL,
            error TEXT,
            downloaded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (backend, model_key)
        );
        "#,
    )
    .execute(pool)
    .await?;

    // Create sessions table
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS sessions (
            session_id SERIAL PRIMARY KEY,
            session_name TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        "#,
    )
    .execute(pool)
    .await?;

    // Create chats table
    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS chats (
            chat_id SERIAL PRIMARY KEY,
            session_id INTEGER NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            chat TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        "#,
    )
    .execute(pool)
    .await?;

    // Create chats index
    let _ = sqlx::query(
        r#"
        CREATE INDEX IF NOT EXISTS chats_session_id_chat_id_idx ON chats (session_id, chat_id DESC);
        "#,
    )
    .execute(pool)
    .await;

    // Clear stale downloads on startup
    let res = sqlx::query(
        r#"
        UPDATE local_models SET status = 'failed', error = 'interrupted'
        WHERE status = 'downloading'
        RETURNING model_key;
        "#,
    )
    .fetch_all(pool)
    .await;

    if let Ok(stale) = res {
        if !stale.is_empty() {
            warn!("Marked {} interrupted downloads as failed on startup", stale.len());
        }
    }

    info!("Database initialized successfully.");
    Ok(())
}
