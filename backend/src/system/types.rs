use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CpuInfo {
    pub model_name: String,
    pub physical_cores: usize,
    pub logical_cores: usize,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MemoryInfo {
    pub total_gb: f64,
    pub free_gb: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DiskInfo {
    pub total_gb: f64,
    pub available_gb: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GpuInfo {
    pub name: String,
    pub vendor: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct OsInfo {
    pub kernel: String,
    pub distro: String,
    pub uts_version: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SystemSpecs {
    pub cpu: CpuInfo,
    pub ram: MemoryInfo,
    pub disk: DiskInfo,
    pub gpus: Vec<GpuInfo>,
    pub os: OsInfo,
}
