use std::fs::File;
use std::io::{BufRead, BufReader};
use super::types::OsInfo;

pub fn get_os_info() -> OsInfo {
    let mut kernel = String::new();
    let mut uts_version = String::new();
    
    // Attempt nix uname call
    if let Ok(u) = nix::sys::utsname::uname() {
        kernel = u.release().to_string_lossy().into_owned();
        uts_version = u.version().to_string_lossy().into_owned();
    } else {
        // Fallbacks
        if let Ok(k) = std::fs::read_to_string("/proc/sys/kernel/osrelease") {
            kernel = k.trim().to_string();
        }
        if let Ok(v) = std::fs::read_to_string("/proc/sys/kernel/version") {
            uts_version = v.trim().to_string();
        }
    }

    // Parse distribution from /etc/os-release
    let mut distro = "Linux".to_string();
    if let Ok(file) = File::open("/etc/os-release") {
        let reader = BufReader::new(file);
        for line in reader.lines().flatten() {
            if line.starts_with("PRETTY_NAME=") {
                let parts: Vec<&str> = line.split('=').collect();
                if parts.len() > 1 {
                    distro = parts[1].trim_matches('"').to_string();
                    break;
                }
            } else if line.starts_with("NAME=") && distro == "Linux" {
                let parts: Vec<&str> = line.split('=').collect();
                if parts.len() > 1 {
                    distro = parts[1].trim_matches('"').to_string();
                }
            }
        }
    }

    OsInfo {
        kernel,
        distro,
        uts_version,
    }
}
