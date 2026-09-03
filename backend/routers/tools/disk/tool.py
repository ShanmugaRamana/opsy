import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("tools.disk")

TIMEOUT = 10
MAX_OUTPUT_CHARS = 4000

# command_id -> (argv, label, description). Fixed allow-list: a caller can only ever select one of
# these ids — it never supplies argv or a shell string itself.
DISK_COMMANDS = {
    "disk_usage": (["df", "-h"], "Disk usage", "Overall disk usage per mounted filesystem"),
    "top_consumers": (
        ["du", "-d", "1", "-h", str(Path.home())],
        "Top space consumers",
        "One-level breakdown of space used under the home directory",
    ),
    "block_devices": (["lsblk"], "Block devices", "Physical disk and partition layout"),
    "docker_usage": (
        ["docker", "system", "df"],
        "Docker disk usage",
        "Docker image/container/volume disk usage (only if Docker is installed)",
    ),
    "log_usage": (
        ["journalctl", "--disk-usage"],
        "Log storage",
        "systemd journal log storage footprint",
    ),
}

_REQUIRES_BINARY = {"docker_usage": "docker", "log_usage": "journalctl"}


def command_label(command_id):
    entry = DISK_COMMANDS.get(command_id)
    return entry[1] if entry else str(command_id)


def tool_schema_properties():
    """Returns {command_id: description}, used to build each provider's tool schema."""
    return {cid: description for cid, (_argv, _label, description) in DISK_COMMANDS.items()}


def execute_disk_command(command_id):
    """Runs the allow-listed command for command_id and returns its output as text. Never raises —
    an unknown id, a missing binary, or a failed/timed-out command all just return a short error
    string, so the caller always has something to work with. (The unknown-id branch is normally
    unreachable when called through the /linux/tools/disk/{command_id} route, which validates first
    and returns 404 instead — kept here for defense-in-depth / standalone use.)"""
    entry = DISK_COMMANDS.get(command_id)
    if entry is None:
        valid = ", ".join(DISK_COMMANDS)
        return f"Error: unknown command '{command_id}'. Valid commands: {valid}."

    argv, label, _description = entry

    required_binary = _REQUIRES_BINARY.get(command_id)
    if required_binary and shutil.which(required_binary) is None:
        return f"{required_binary} is not installed on this system."

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"{label} ({' '.join(argv)}) failed: {e}")
        return f"Error running {label}: {e}"

    output = result.stdout.strip()
    if result.returncode != 0:
        output = (f"{output}\n{result.stderr.strip()}").strip() or f"{label} exited with code {result.returncode}"

    return output[:MAX_OUTPUT_CHARS]
