use nix::sys::statvfs::statvfs;
use super::types::DiskInfo;

pub fn get_disk_info() -> DiskInfo {
    match statvfs("/") {
        Ok(stats) => {
            let total = stats.blocks() as f64 * stats.fragment_size() as f64;
            let available = stats.blocks_free() as f64 * stats.fragment_size() as f64;

            let total_gb = total / 1024.0 / 1024.0 / 1024.0;
            let available_gb = available / 1024.0 / 1024.0 / 1024.0;

            DiskInfo {
                total_gb: (total_gb * 100.0).round() / 100.0,
                available_gb: (available_gb * 100.0).round() / 100.0,
            }
        }
        Err(_) => DiskInfo {
            total_gb: 0.0,
            available_gb: 0.0,
        },
    }
}
