pub mod types;
mod cpu;
mod memory;
mod disk;
mod gpu;
mod os;

use types::SystemSpecs;

pub fn get_system_specs() -> SystemSpecs {
    SystemSpecs {
        cpu: cpu::get_cpu_info(),
        ram: memory::get_memory_info(),
        disk: disk::get_disk_info(),
        gpus: gpu::get_gpu_info(),
        os: os::get_os_info(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_system_specs() {
        let specs = get_system_specs();
        assert!(!specs.cpu.model_name.is_empty());
        assert!(specs.ram.total_gb > 0.0);
        assert!(specs.disk.total_gb > 0.0);
    }
}
