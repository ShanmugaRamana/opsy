use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::GpuInfo;
use crate::system::infra::gpu_scanner;

pub struct GetGpuStatsQuery;

impl Query for GetGpuStatsQuery {
    type Output = Vec<GpuInfo>;
}

pub struct GetGpuStatsHandler;

impl QueryHandler<GetGpuStatsQuery> for GetGpuStatsHandler {
    fn handle(&self, _query: GetGpuStatsQuery) -> Pin<Box<dyn Future<Output = Result<Vec<GpuInfo>, AppError>> + Send>> {
        Box::pin(async move {
            let gpu_info = gpu_scanner::scan_gpu();
            Ok(gpu_info)
        })
    }
}
