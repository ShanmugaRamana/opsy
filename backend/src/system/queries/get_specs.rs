use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::SystemSpecs;
use crate::system::infra::{cpu_scanner, disk_scanner, gpu_scanner, memory_scanner, os_scanner};

pub struct GetSystemSpecsQuery;

impl Query for GetSystemSpecsQuery {
    type Output = SystemSpecs;
}

pub struct GetSystemSpecsHandler;

impl QueryHandler<GetSystemSpecsQuery> for GetSystemSpecsHandler {
    fn handle(&self, _query: GetSystemSpecsQuery) -> Pin<Box<dyn Future<Output = Result<SystemSpecs, AppError>> + Send>> {
        Box::pin(async move {
            let specs = SystemSpecs {
                cpu: cpu_scanner::scan_cpu(),
                ram: memory_scanner::scan_memory(),
                disk: disk_scanner::scan_disk(),
                gpus: gpu_scanner::scan_gpu(),
                os: os_scanner::scan_os(),
            };
            Ok(specs)
        })
    }
}
