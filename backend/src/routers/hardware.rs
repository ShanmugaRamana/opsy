use axum::Json;
use serde::Serialize;
use std::fs;
use std::process::Command;
use sysinfo::{CpuRefreshKind, Disks, MemoryRefreshKind, RefreshKind, System};

#[derive(Serialize)]
pub struct CPUInfo {
    pub model: Option<String>,
    pub cores: Option<usize>,
    pub usage_percent: Option<f32>,
}

#[derive(Serialize)]
pub struct RAMInfo {
    pub total_gb: Option<f64>,
    pub used_gb: Option<f64>,
}

#[derive(Serialize)]
pub struct GPUInfo {
    pub model: Option<String>,
    pub dedicated: Option<bool>,
    pub usage_percent: Option<f32>,
    pub vram_gb: Option<f64>,
}

#[derive(Serialize)]
pub struct StorageInfo {
    pub total_gb: Option<f64>,
    pub free_gb: Option<f64>,
}

#[derive(Serialize)]
pub struct HardwareProfile {
    pub os: Option<String>,
    pub cpu: CPUInfo,
    pub ram: RAMInfo,
    pub gpu: Option<GPUInfo>,
    pub storage: StorageInfo,
}

#[derive(Serialize)]
pub struct Insight {
    pub id: String,
    pub title: String,
    pub detail: String,
    pub severity: String,
}

#[derive(Serialize)]
pub struct InsightsResponse {
    pub insights: Vec<Insight>,
}

fn get_os_name() -> Option<String> {
    if let Ok(content) = fs::read_to_string("/etc/os-release") {
        for line in content.lines() {
            if let Some(stripped) = line.strip_prefix("PRETTY_NAME=") {
                return Some(stripped.trim_matches('"').to_string());
            }
        }
    }
    System::name()
}

fn get_cpu_model() -> Option<String> {
    if let Ok(content) = fs::read_to_string("/proc/cpuinfo") {
        for line in content.lines() {
            if line.to_lowercase().starts_with("model name") {
                if let Some((_, val)) = line.split_once(':') {
                    return Some(val.trim().to_string());
                }
            }
        }
    }
    None
}

fn get_gpu() -> Option<GPUInfo> {
    let output = Command::new("lspci").output().ok()?;
    let text = String::from_utf8_lossy(&output.stdout);
    for line in text.lines() {
        if line.contains("VGA compatible controller") || line.contains("3D controller") {
            let model = line.split(':').last().unwrap_or("").trim().to_string();
            let lower = model.to_lowercase();
            let virtual_markers = ["virtio", "qxl", "vmware", "virtualbox", "bochs", "cirrus", "llvmpipe", "swrast"];
            let dedicated = !virtual_markers.iter().any(|m| lower.contains(m));

            let mut usage = None;
            let mut vram = None;

            if lower.contains("nvidia") {
                if let Ok(smi_out) = Command::new("nvidia-smi")
                    .args(["--query-gpu=utilization.gpu,memory.total", "--format=csv,noheader,nounits"])
                    .output()
                {
                    let smi_text = String::from_utf8_lossy(&smi_out.stdout);
                    if let Some(first_line) = smi_text.lines().next() {
                        let parts: Vec<&str> = first_line.split(',').map(|s| s.trim()).collect();
                        if parts.len() >= 2 {
                            usage = parts[0].parse::<f32>().ok();
                            if let Ok(mib) = parts[1].parse::<f64>() {
                                vram = Some((mib / 1024.0 * 10.0).round() / 10.0);
                            }
                        }
                    }
                }
            }

            return Some(GPUInfo {
                model: Some(model),
                dedicated: Some(dedicated),
                usage_percent: usage,
                vram_gb: vram,
            });
        }
    }
    None
}

pub fn collect_profile() -> HardwareProfile {
    let mut sys = System::new_with_specifics(
        RefreshKind::new()
            .with_cpu(CpuRefreshKind::everything())
            .with_memory(MemoryRefreshKind::everything()),
    );
    std::thread::sleep(std::time::Duration::from_millis(200));
    sys.refresh_cpu();

    let os = get_os_name();
    let cpu_model = get_cpu_model();
    let cpu_cores = sys.physical_core_count().or_else(|| Some(sys.cpus().len()));
    let cpu_usage = sys.global_cpu_info().cpu_usage();

    let total_ram_gb = (sys.total_memory() as f64 / (1024.0 * 1024.0 * 1024.0) * 10.0).round() / 10.0;
    let used_ram_gb = (sys.used_memory() as f64 / (1024.0 * 1024.0 * 1024.0) * 10.0).round() / 10.0;

    let disks = Disks::new_with_refreshed_list();
    let root_disk = disks.iter().find(|d| d.mount_point() == std::path::Path::new("/"));
    let (total_storage, free_storage) = if let Some(d) = root_disk {
        (
            Some((d.total_space() as f64 / (1024.0 * 1024.0 * 1024.0) * 10.0).round() / 10.0),
            Some((d.available_space() as f64 / (1024.0 * 1024.0 * 1024.0) * 10.0).round() / 10.0),
        )
    } else {
        (None, None)
    };

    let gpu = get_gpu();

    HardwareProfile {
        os,
        cpu: CPUInfo {
            model: cpu_model,
            cores: cpu_cores,
            usage_percent: Some(cpu_usage),
        },
        ram: RAMInfo {
            total_gb: Some(total_ram_gb),
            used_gb: Some(used_ram_gb),
        },
        gpu,
        storage: StorageInfo {
            total_gb: total_storage,
            free_gb: free_storage,
        },
    }
}

pub async fn get_hardware_profile() -> Json<HardwareProfile> {
    Json(collect_profile())
}

pub async fn get_hardware_insights() -> Json<InsightsResponse> {
    let profile = collect_profile();
    let mut insights = Vec::new();

    // Memory Capacity Insight
    if let Some(total) = profile.ram.total_gb {
        let (detail, severity) = if total < 8.0 {
            (format!("{} GB of RAM is on the lower end — expect limited headroom for memory-intensive workloads.", total), "warn")
        } else if total < 16.0 {
            (format!("{} GB of RAM offers moderate headroom for memory-intensive workloads.", total), "good")
        } else if total < 32.0 {
            (format!("{} GB of RAM offers ample headroom for memory-intensive workloads.", total), "good")
        } else {
            (format!("{} GB of RAM offers substantial headroom, even for demanding workloads.", total), "good")
        };
        insights.push(Insight {
            id: "memory_capacity".to_string(),
            title: "Memory Capacity".to_string(),
            detail,
            severity: severity.to_string(),
        });
    }

    // Acceleration Insight
    if let Some(ref gpu) = profile.gpu {
        if gpu.dedicated.unwrap_or(false) {
            insights.push(Insight {
                id: "acceleration".to_string(),
                title: "GPU Acceleration".to_string(),
                detail: format!("A dedicated GPU ({}) was detected, enabling hardware acceleration.", gpu.model.as_deref().unwrap_or("GPU")),
                severity: "good".to_string(),
            });
        } else {
            let cores_text = profile.cpu.cores.map(|c| format!("{} CPU cores", c)).unwrap_or_else(|| "the CPU".to_string());
            insights.push(Insight {
                id: "acceleration".to_string(),
                title: "No Dedicated GPU".to_string(),
                detail: format!("No dedicated GPU detected — this machine relies on {} for compute.", cores_text),
                severity: "info".to_string(),
            });
        }
    }

    // Storage Headroom Insight
    if let Some(free) = profile.storage.free_gb {
        let (detail, severity) = if free < 10.0 {
            (format!("Only {} GB free — disk space is running low.", free), "warn")
        } else {
            (format!("{} GB free — plenty of headroom on disk.", free), "good")
        };
        insights.push(Insight {
            id: "storage".to_string(),
            title: "Storage Headroom".to_string(),
            detail,
            severity: severity.to_string(),
        });
    }

    // Memory Pressure Insight
    if let (Some(total), Some(used)) = (profile.ram.total_gb, profile.ram.used_gb) {
        if total > 0.0 && (used / total) > 0.85 {
            insights.push(Insight {
                id: "memory_pressure".to_string(),
                title: "Memory Pressure".to_string(),
                detail: "Memory is nearly full — close other applications to free up headroom.".to_string(),
                severity: "warn".to_string(),
            });
        }
    }

    Json(InsightsResponse { insights })
}
