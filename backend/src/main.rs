mod config;
mod crypto;
mod db;
mod error;
mod routers;
pub mod system_tools;

use axum::routing::{delete, get, post, put};
use axum::Router;
use std::net::SocketAddr;
use tower_http::cors::{Any, CorsLayer};
use tracing::info;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "zyros_backend=info,tower_http=info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let cfg = config::Config::from_env();
    info!("Starting Zyros Backend on {}:{}", cfg.host, cfg.port);

    let database_url = cfg.database_url();
    info!("Connecting to PostgreSQL at {}:{}/{}...", cfg.db_host, cfg.db_port, cfg.db_name);

    let pool = match db::create_pool(&database_url).await {
        Ok(p) => {
            if let Err(e) = db::init_db(&p).await {
                tracing::warn!("Could not run initial DB migrations: {}", e);
            }
            p
        }
        Err(e) => {
            tracing::warn!("Database unavailable on boot (will retry lazily): {}", e);
            // Create an empty pool or retry
            db::create_pool(&database_url).await.unwrap_or_else(|_| {
                panic!("Failed to configure DB pool: {}", e);
            })
        }
    };

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app_state = (pool.clone(), cfg.clone());

    let app = Router::new()
        // Root & Health & System
        .route("/", get(routers::root::root))
        .route("/health", get(routers::health::health))
        .route("/shutdown", post(routers::system::shutdown))
        // Onboarding
        .route("/linux/onboarding/verify", get(routers::onboarding::verify_onboarding).with_state(pool.clone()))
        .route("/linux/onboarding/user", post(routers::onboarding::create_onboarding_user).with_state(pool.clone()))
        // User & Preferences
        .route("/linux/users", get(routers::user::list_all_users).with_state(pool.clone()))
        .route("/linux/users/preferences", get(routers::user::read_preferences).with_state(pool.clone()))
        .route("/linux/users/preferences", put(routers::user::update_preferences).with_state(pool.clone()))
        // Hardware
        .route("/linux/hardware/profile", get(routers::hardware::get_hardware_profile))
        .route("/linux/hardware/profile/insights", get(routers::hardware::get_hardware_insights))
        // Models
        .route("/linux/models", get(routers::models::list_all_models).with_state(pool.clone()))
        // Local models
        .route("/linux/local-models/environment", get(routers::local_models::get_environment).with_state(app_state.clone()))
        .route("/linux/local-models/recommendations", get(routers::local_models::get_recommendations).with_state(app_state.clone()))
        .route("/linux/local-models/catalog", get(routers::local_models::get_catalog))
        .route("/linux/local-models/", get(routers::local_models::list_installed_local_models).with_state(app_state.clone()))
        .route("/linux/local-models/download", post(routers::local_models::start_download).with_state(app_state.clone()))
        .route("/linux/local-models/download/cancel", post(routers::local_models::cancel_download))
        .route("/linux/local-models/download/ws", get(routers::local_models::download_ws_handler))
        .route("/linux/local-models/:model_key", delete(routers::local_models::delete_local_model).with_state(app_state.clone()))
        // BYOK
        .route("/linux/byok/key", post(routers::byok::verify_and_store_key).with_state(pool.clone()))
        .route("/linux/byok/key/:provider", delete(routers::byok::delete_key_route).with_state(pool.clone()))
        .route("/linux/byok/keys", get(routers::byok::list_configured_keys).with_state(pool.clone()))
        // Sessions
        .route("/linux/sessions", get(routers::sessions::list_sessions).with_state(pool.clone()))
        .route("/linux/sessions/:session_id/chats", get(routers::sessions::get_session_chats).with_state(pool.clone()))
        .route("/linux/sessions/:session_id/activate", post(routers::sessions::activate_session).with_state(pool.clone()))
        // Orchestrator, Catalogs, Permissions, WS
        .route("/linux/orchestrator/permissions/:request_id", post(routers::orchestrator::decide_permission))
        .route("/linux/orchestrator/run", post(routers::orchestrator::run_turn).with_state(app_state.clone()))
        .route("/linux/orchestrator/ws", get(routers::orchestrator::orchestrator_ws_handler).with_state(app_state.clone()))
        .route("/linux/agents/", get(routers::orchestrator::list_agents_catalog))
        .route("/linux/tools/", get(routers::orchestrator::list_tools_catalog))
        .route("/linux/memory/", get(routers::orchestrator::list_memory_catalog))
        .route("/linux/orchestrator/supervisor/", get(routers::orchestrator::describe_supervisor))
        .layer(cors);

    let addr: SocketAddr = format!("{}:{}", cfg.host, cfg.port).parse()?;
    info!("Zyros backend server running at http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app.into_make_service()).await?;

    Ok(())
}
