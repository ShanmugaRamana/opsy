pub mod domain;
pub mod queries;
pub(crate) mod infra;
pub mod http;

#[allow(unused_imports)]
pub use domain::{CpuInfo, DiskInfo, GpuInfo, MemoryInfo, OsInfo, SystemSpecs};
pub use queries::register_queries;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shared::bus::QueryBus;
    use crate::system::queries::GetSystemSpecsQuery;

    #[tokio::test]
    async fn test_get_system_specs_query() {
        let query_bus = register_queries(QueryBus::builder()).build();
        let specs = query_bus.dispatch(GetSystemSpecsQuery).await.expect("Failed to get specs");
        assert!(!specs.cpu.model_name.is_empty());
        assert!(specs.ram.total_gb > 0.0);
        assert!(specs.disk.total_gb > 0.0);
    }
}
