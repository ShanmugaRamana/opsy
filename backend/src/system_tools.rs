use std::process::Command;

pub fn execute_system_query(cmd_str: &str) -> Option<String> {
    let output = Command::new("sh")
        .arg("-c")
        .arg(cmd_str)
        .output()
        .ok()?;

    if output.status.success() {
        Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
    } else {
        None
    }
}

pub fn get_system_context(user_query: &str) -> String {
    let mut ctx = Vec::new();

    // Base System Information
    if let Some(os) = execute_system_query("cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'") {
        ctx.push(format!("Operating System (OS): {}", os));
    }
    if let Some(kernel) = execute_system_query("uname -r") {
        ctx.push(format!("Linux Kernel: {}", kernel));
    }
    if let Some(arch) = execute_system_query("uname -m") {
        ctx.push(format!("Architecture: {}", arch));
    }
    if let Some(hostname) = execute_system_query("hostname") {
        ctx.push(format!("Hostname: {}", hostname));
    }
    if let Some(user) = execute_system_query("whoami") {
        ctx.push(format!("Current User: {}", user));
    }
    if let Some(uptime) = execute_system_query("uptime -p") {
        ctx.push(format!("System Uptime: {}", uptime));
    }
    if let Some(cpu) = execute_system_query("lscpu | grep 'Model name:' | head -n 1 | sed 's/Model name:[ \t]*//'") {
        let cores = execute_system_query("nproc").unwrap_or_else(|| "unknown".to_string());
        ctx.push(format!("CPU: {} ({} cores)", cpu, cores));
    }
    if let Some(mem) = execute_system_query("free -h | awk '/^Mem:/ {print \"Total: \" $2 \", Used: \" $3 \", Free: \" $4 \", Available: \" $7}'") {
        ctx.push(format!("Memory (RAM): {}", mem));
    }
    if let Some(swap) = execute_system_query("free -h | awk '/^Swap:/ {print \"Total: \" $2 \", Used: \" $3 \", Free: \" $4}'") {
        ctx.push(format!("Swap Space: {}", swap));
    }
    if let Some(disk) = execute_system_query("df -h / | awk 'NR==2 {print \"Total: \" $2 \", Used: \" $3 \", Available: \" $4 \", Use%: \" $5}'") {
        ctx.push(format!("Root Disk Space (/): {}", disk));
    }
    if let Some(ip) = execute_system_query("ip -br addr | grep -v 'LOOPBACK\\|DOWN' | head -n 4") {
        ctx.push(format!("Network Interfaces & IPs:\n{}", ip));
    }

    let q_lower = user_query.to_lowercase();

    // Query-specific dynamic diagnostics
    if q_lower.contains("disk") || q_lower.contains("storage") || q_lower.contains("space") || q_lower.contains("partition") || q_lower.contains("drive") {
        if let Some(all_disks) = execute_system_query("df -h -x tmpfs -x devtmpfs -x squashfs") {
            ctx.push(format!("\nDetailed Filesystem & Storage:\n{}", all_disks));
        }
        if let Some(lsblk) = execute_system_query("lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT 2>/dev/null | head -n 15") {
            ctx.push(format!("\nBlock Devices (lsblk):\n{}", lsblk));
        }
    }

    if q_lower.contains("process") || q_lower.contains("running") || q_lower.contains("cpu") || q_lower.contains("task") || q_lower.contains("top") || q_lower.contains("load") {
        if let Some(load) = execute_system_query("uptime | awk -F'load average:' '{print $2}'") {
            ctx.push(format!("Load Average: {}", load.trim()));
        }
        if let Some(procs) = execute_system_query("ps aux --sort=-%cpu | head -n 10 | awk '{printf \"%-12s %-6s %-6s %-6s %s\\n\", $1, $2, $3\"%\", $4\"%\", $11}'") {
            ctx.push(format!("\nTop Running Processes (by CPU):\nUSER         PID    CPU%   MEM%   COMMAND\n{}", procs));
        }
        if let Some(mem_procs) = execute_system_query("ps aux --sort=-%mem | head -n 10 | awk '{printf \"%-12s %-6s %-6s %-6s %s\\n\", $1, $2, $3\"%\", $4\"%\", $11}'") {
            ctx.push(format!("\nTop Running Processes (by Memory):\nUSER         PID    CPU%   MEM%   COMMAND\n{}", mem_procs));
        }
    }

    if q_lower.contains("network") || q_lower.contains("port") || q_lower.contains("ip") || q_lower.contains("dns") || q_lower.contains("connection") || q_lower.contains("listen") {
        if let Some(ports) = execute_system_query("ss -tuln 2>/dev/null | head -n 12") {
            ctx.push(format!("\nOpen/Listening Ports:\n{}", ports));
        }
        if let Some(routes) = execute_system_query("ip route | head -n 5") {
            ctx.push(format!("\nRouting Table:\n{}", routes));
        }
    }

    if q_lower.contains("package") || q_lower.contains("installed") || q_lower.contains("software") || q_lower.contains("version") {
        if let Some(pkg_mgr) = execute_system_query("which pacman apt dnf apk zypper 2>/dev/null | head -n 1") {
            ctx.push(format!("Package Manager: {}", pkg_mgr));
        }
    }

    ctx.join("\n")
}
