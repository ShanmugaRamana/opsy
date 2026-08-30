use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::MemoryInfo;
use crate::system::infra::memory_scanner;

pub struct GetMemoryStatsQuery;

impl Query for GetMemoryStatsQuery {
    type Output = MemoryInfo;
}

pub struct GetMemoryStatsHandler;

impl QueryHandler<GetMemoryStatsQuery> for GetMemoryStatsHandler {
    fn handle(&self, _query: GetMemoryStatsQuery) -> Pin<Box<dyn Future<Output = Result<MemoryInfo, AppError>> + Send>> {
        Box::pin(async move {
            let memory_info = memory_scanner::scan_memory();
            Ok(memory_info)
        })
    }
}
