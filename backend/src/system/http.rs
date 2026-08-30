use axum::extract::State;
use axum::Json;
use tracing::info;
use crate::shared::bus::QueryBus;
use crate::shared::error::AppError;
use crate::system::domain::SystemSpecs;
use crate::system::queries::GetSystemSpecsQuery;

pub async fn specs_handler(
    State(query_bus): State<QueryBus>,
) -> Result<Json<SystemSpecs>, AppError> {
    info!("GET /onboard/specs requested");
    let specs = query_bus.dispatch(GetSystemSpecsQuery).await?;
    Ok(Json(specs))
}
