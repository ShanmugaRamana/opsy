use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::OsInfo;
use crate::system::infra::os_scanner;

pub struct GetOsStatsQuery;

impl Query for GetOsStatsQuery {
    type Output = OsInfo;
}

pub struct GetOsStatsHandler;

impl QueryHandler<GetOsStatsQuery> for GetOsStatsHandler {
    fn handle(&self, _query: GetOsStatsQuery) -> Pin<Box<dyn Future<Output = Result<OsInfo, AppError>> + Send>> {
        Box::pin(async move {
            let os_info = os_scanner::scan_os();
            Ok(os_info)
        })
    }
}
