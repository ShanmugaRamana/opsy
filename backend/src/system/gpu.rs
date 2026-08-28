use std::fs;
use std::path::Path;
use super::types::GpuInfo;

pub fn get_gpu_info() -> Vec<GpuInfo> {
    let mut gpus = Vec::new();
    let drm_path = Path::new("/sys/class/drm");
    if !drm_path.exists() {
        return gpus;
    }

    if let Ok(entries) = fs::read_dir(drm_path) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            // Only examine primary GPU devices (e.g., card0, card1)
            if !name.starts_with("card") || name.contains('-') {
                continue;
            }

            let device_path = entry.path().join("device");
            let vendor_file = device_path.join("vendor");
            let device_file = device_path.join("device");

            if vendor_file.exists() && device_file.exists() {
                let vendor = fs::read_to_string(&vendor_file)
                    .map(|s| s.trim().to_lowercase())
                    .unwrap_or_default();
                let device = fs::read_to_string(&device_file)
                    .map(|s| s.trim().to_lowercase())
                    .unwrap_or_default();

                let uevent_file = device_path.join("uevent");
                let mut driver = String::new();
                if let Ok(uevent_content) = fs::read_to_string(uevent_file) {
                    for line in uevent_content.lines() {
                        if line.starts_with("DRIVER=") {
                            driver = line.replace("DRIVER=", "").trim().to_string();
                            break;
                        }
                    }
                }

                let vendor_name = match vendor.as_str() {
                    "0x8086" => "Intel Corporation",
                    "0x10de" => "NVIDIA Corporation",
                    "0x1002" => "Advanced Micro Devices, Inc. (AMD)",
                    _ => "Unknown Vendor",
                };

                let gpu_name = if !driver.is_empty() {
                    format!("Graphics Controller (Driver: {}, Device: {})", driver, device)
                } else {
                    format!("Graphics Controller (Device: {})", device)
                };

                gpus.push(GpuInfo {
                    name: gpu_name,
                    vendor: vendor_name.to_string(),
                });
            }
        }
    }

    gpus.dedup_by(|a, b| a.name == b.name && a.vendor == b.vendor);
    gpus
}
