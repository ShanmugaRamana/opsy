use std::fs::File;
use std::io::{BufRead, BufReader};
use crate::system::domain::CpuInfo;

pub fn scan_cpu() -> CpuInfo {
    let file = match File::open("/proc/cpuinfo") {
        Ok(f) => f,
        Err(_) => {
            return CpuInfo {
                model_name: "Unknown CPU".to_string(),
                physical_cores: 1,
                logical_cores: 1,
            };
        }
    };

    let reader = BufReader::new(file);
    let mut model_name = String::new();
    let mut processor_count = 0;
    let mut cpu_cores = 0;

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
        let val = parts[1].trim();

        if key == "model name" && model_name.is_empty() {
            model_name = val.to_string();
        } else if key == "processor" {
            processor_count += 1;
        } else if key == "cpu cores" {
            if let Ok(cores) = val.parse::<usize>() {
                cpu_cores = cores;
            }
        }
    }

    if model_name.is_empty() {
        model_name = "Unknown Linux CPU".to_string();
    }

    let physical_cores = if cpu_cores > 0 { cpu_cores } else { processor_count.max(1) };
    let logical_cores = processor_count.max(1);

    CpuInfo {
        model_name,
        physical_cores,
        logical_cores,
    }
}
