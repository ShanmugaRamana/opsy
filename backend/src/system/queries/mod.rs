pub mod get_cpu;
pub mod get_memory;
pub mod get_disk;
pub mod get_gpu;
pub mod get_os;
pub mod get_specs;

#[allow(unused_imports)]
pub use get_cpu::{GetCpuStatsHandler, GetCpuStatsQuery};
#[allow(unused_imports)]
pub use get_disk::{GetDiskStatsHandler, GetDiskStatsQuery};
#[allow(unused_imports)]
pub use get_gpu::{GetGpuStatsHandler, GetGpuStatsQuery};
#[allow(unused_imports)]
pub use get_memory::{GetMemoryStatsHandler, GetMemoryStatsQuery};
#[allow(unused_imports)]
pub use get_os::{GetOsStatsHandler, GetOsStatsQuery};
pub use get_specs::{GetSystemSpecsHandler, GetSystemSpecsQuery};

use crate::shared::bus::QueryBusBuilder;

pub fn register_queries(builder: QueryBusBuilder) -> QueryBusBuilder {
    builder
        .register(GetCpuStatsHandler)
        .register(GetMemoryStatsHandler)
        .register(GetDiskStatsHandler)
        .register(GetGpuStatsHandler)
        .register(GetOsStatsHandler)
        .register(GetSystemSpecsHandler)
}
