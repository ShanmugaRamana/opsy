use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::CpuInfo;
use crate::system::infra::cpu_scanner;

pub struct GetCpuStatsQuery;

impl Query for GetCpuStatsQuery {
    type Output = CpuInfo;
}

pub struct GetCpuStatsHandler;

impl QueryHandler<GetCpuStatsQuery> for GetCpuStatsHandler {
    fn handle(&self, _query: GetCpuStatsQuery) -> Pin<Box<dyn Future<Output = Result<CpuInfo, AppError>> + Send>> {
        Box::pin(async move {
            let cpu_info = cpu_scanner::scan_cpu();
            Ok(cpu_info)
        })
    }
}
