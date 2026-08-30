use std::fs::File;
use std::io::{BufRead, BufReader};
use crate::system::domain::MemoryInfo;

pub fn scan_memory() -> MemoryInfo {
    let file = match File::open("/proc/meminfo") {
        Ok(f) => f,
        Err(_) => {
            return MemoryInfo {
                total_gb: 0.0,
                free_gb: 0.0,
            };
        }
    };

    let reader = BufReader::new(file);
    let mut total_kb = 0.0;
    let mut available_kb = 0.0;

    for line in reader.lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => continue,
        };
        let parts: Vec<&str> = line.split(':').collect();
        if parts.len() < 2 {
            continue;
        }
        let key = parts[0].trim();
        let val_part = parts[1].trim();
        
        let val_num = val_part
            .split_whitespace()
            .next()
            .unwrap_or("0")
            .parse::<f64>()
            .unwrap_or(0.0);

        if key == "MemTotal" {
            total_kb = val_num;
        } else if key == "MemAvailable" {
            available_kb = val_num;
        }
    }

    let total_gb = total_kb / 1024.0 / 1024.0;
    let free_gb = available_kb / 1024.0 / 1024.0;

    MemoryInfo {
        total_gb: (total_gb * 100.0).round() / 100.0,
        free_gb: (free_gb * 100.0).round() / 100.0,
    }
}
