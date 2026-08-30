use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::DiskInfo;
use crate::system::infra::disk_scanner;

pub struct GetDiskStatsQuery;

impl Query for GetDiskStatsQuery {
    type Output = DiskInfo;
}

pub struct GetDiskStatsHandler;

impl QueryHandler<GetDiskStatsQuery> for GetDiskStatsHandler {
    fn handle(&self, _query: GetDiskStatsQuery) -> Pin<Box<dyn Future<Output = Result<DiskInfo, AppError>> + Send>> {
        Box::pin(async move {
            let disk_info = disk_scanner::scan_disk();
            Ok(disk_info)
        })
    }
}
