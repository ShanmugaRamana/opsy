import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("tools.disk")

MAX_OUTPUT_CHARS = 6000
PATH_TOKEN = "{path}"


@dataclass(frozen=True)
class DiskCommand:
    """One allow-listed observation. Either runs a fixed argv (kind="command") or reads a fixed file
    (kind="file"). The caller only ever selects an id — it never supplies argv, a shell string, or a
    file path of its own."""

    label: str
    description: str
    kind: str = "command"
    argv: tuple = ()
    file_path: str = ""
    path_mode: str = "none"  # none | optional | required
    default_path: str = ""
    requires: str = ""  # binary that must be present
    timeout: int = 10
    needs_root: bool = False
    postprocess: str = ""


def _home():
    return str(Path.home())


DISK_COMMANDS: dict[str, DiskCommand] = {
    # ---- Capacity ----
    "disk_usage": DiskCommand(
        "Disk usage", "Free/used space per mounted filesystem. The default starting point.",
        argv=("df", "-h", PATH_TOKEN), path_mode="optional",
    ),
    "disk_usage_types": DiskCommand(
        "Disk usage with filesystem types", "Like disk_usage but also shows each filesystem's type.",
        argv=("df", "-Th"),
    ),
    "inode_usage": DiskCommand(
        "Inode usage", "Inode consumption. Use when space looks free but writes fail with 'no space left'.",
        argv=("df", "-i", PATH_TOKEN), path_mode="optional",
    ),
    "boot_usage": DiskCommand(
        "Boot partition usage", "Space on /boot, which old kernels commonly fill.",
        argv=("df", "-h", "/boot"),
    ),
    # ---- What is consuming space ----
    "dir_usage": DiskCommand(
        "Directory usage", "One-level size breakdown of a directory. The main drill-down tool.",
        argv=("du", "-d", "1", "-h", PATH_TOKEN), path_mode="optional", default_path=_home(), timeout=30,
    ),
    "dir_usage_deep": DiskCommand(
        "Directory usage (2 levels)", "Two-level size breakdown of a directory.",
        argv=("du", "-d", "2", "-h", PATH_TOKEN), path_mode="optional", default_path=_home(), timeout=45,
    ),
    "largest_dirs": DiskCommand(
        "Largest directories", "The biggest directories anywhere under a path, sorted by size.",
        argv=("du", "-d", "3", PATH_TOKEN), path_mode="optional", default_path=_home(),
        timeout=60, postprocess="sort_du",
    ),
    "largest_files": DiskCommand(
        "Largest files", "Individual files over 100MB under a path, largest first.",
        argv=("find", PATH_TOKEN, "-xdev", "-type", "f", "-size", "+100M"),
        path_mode="optional", default_path=_home(), timeout=60, postprocess="size_paths",
    ),
    "old_large_files": DiskCommand(
        "Old large files", "Files over 100MB not accessed in 180+ days. Good cleanup candidates.",
        argv=("find", PATH_TOKEN, "-xdev", "-type", "f", "-size", "+100M", "-atime", "+180"),
        path_mode="optional", default_path=_home(), timeout=60, postprocess="size_paths",
    ),
    "deleted_open_files": DiskCommand(
        "Deleted but open files", "Space held by deleted files still held open by a process. Explains "
        "'df says full but du disagrees'.",
        argv=("lsof", "+L1"), requires="lsof", timeout=30, needs_root=True,
    ),
    "tmp_usage": DiskCommand("Temp directory usage", "Size of /tmp.", argv=("du", "-sh", "/tmp"), timeout=30),
    "var_tmp_usage": DiskCommand("Persistent temp usage", "Size of /var/tmp.", argv=("du", "-sh", "/var/tmp"), timeout=30),
    "var_usage": DiskCommand("System /var usage", "One-level breakdown of /var.", argv=("du", "-d", "1", "-h", "/var"), timeout=45),
    "home_usage": DiskCommand("All home directories", "Per-user home directory sizes.", argv=("du", "-d", "1", "-h", "/home"), timeout=45),
    "log_dir_usage": DiskCommand("Log directory usage", "Size of /var/log.", argv=("du", "-sh", "/var/log"), timeout=30),
    # ---- Devices, partitions, layout ----
    "block_devices": DiskCommand(
        "Block devices", "Disks and partitions with size, type, filesystem and mount point.",
        argv=("lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL"),
    ),
    "disk_hardware": DiskCommand(
        "Disk hardware", "Physical drives with model, serial, and whether they are rotational (HDD) or SSD.",
        argv=("lsblk", "-d", "-o", "NAME,SIZE,ROTA,MODEL,SERIAL"),
    ),
    "filesystem_overview": DiskCommand(
        "Filesystem overview", "Filesystem type, label, UUID and mount point per device.",
        argv=("lsblk", "-f"),
    ),
    "partition_table": DiskCommand(
        "Partition table", "Partition layout including unallocated free space.",
        argv=("parted", "-l"), requires="parted", needs_root=True,
    ),
    "fdisk_list": DiskCommand(
        "Partition list (fdisk)", "Alternative partition table view.",
        argv=("fdisk", "-l"), requires="fdisk", needs_root=True,
    ),
    "device_ids": DiskCommand(
        "Device identifiers", "UUIDs, labels and filesystem types per block device.",
        argv=("blkid",), requires="blkid", needs_root=True,
    ),
    "nvme_devices": DiskCommand("NVMe devices", "NVMe drives and their namespaces.", argv=("nvme", "list"), requires="nvme"),
    "scsi_devices": DiskCommand("SCSI/SATA devices", "SCSI and SATA attached devices.", argv=("lsscsi",), requires="lsscsi"),
    # ---- Mounts and configuration ----
    "mounts": DiskCommand("Mounts", "What is mounted where, with filesystem types and options.", argv=("findmnt",), requires="findmnt"),
    "mount_table": DiskCommand("Raw mount table", "Kernel's own mount table.", kind="file", file_path="/proc/mounts"),
    "fstab": DiskCommand(
        "Mount configuration", "What is configured to mount at boot, which may differ from what is mounted now.",
        kind="file", file_path="/etc/fstab",
    ),
    "tmpfs_mounts": DiskCommand(
        "RAM-backed mounts", "tmpfs mounts, which consume memory rather than disk.",
        argv=("findmnt", "-t", "tmpfs"), requires="findmnt",
    ),
    "network_mounts": DiskCommand(
        "Network mounts", "NFS/CIFS/SMB network filesystems.",
        argv=("findmnt", "-t", "nfs,nfs4,cifs,smb3"), requires="findmnt",
    ),
    "systemd_mounts": DiskCommand(
        "systemd mount units", "Mount units managed by systemd, including failed ones.",
        argv=("systemctl", "list-units", "--type=mount", "--no-pager"), requires="systemctl",
    ),
    # ---- Advanced filesystems ----
    "lvm_logical": DiskCommand("LVM logical volumes", "LVM logical volumes and sizes.", argv=("lvs",), requires="lvs", needs_root=True),
    "lvm_groups": DiskCommand("LVM volume groups", "LVM volume groups and free extents.", argv=("vgs",), requires="vgs", needs_root=True),
    "lvm_physical": DiskCommand("LVM physical volumes", "Physical volumes backing LVM groups.", argv=("pvs",), requires="pvs", needs_root=True),
    "raid_status": DiskCommand("Software RAID status", "mdraid array state and rebuild progress.", kind="file", file_path="/proc/mdstat"),
    "raid_detail": DiskCommand("RAID details", "Detailed mdraid array configuration.", argv=("mdadm", "--detail", "--scan"), requires="mdadm", needs_root=True),
    "btrfs_usage": DiskCommand(
        "Btrfs usage", "True btrfs space usage, which plain df reports misleadingly.",
        argv=("btrfs", "filesystem", "usage", PATH_TOKEN), path_mode="optional", default_path="/",
        requires="btrfs", needs_root=True,
    ),
    "btrfs_subvolumes": DiskCommand(
        "Btrfs subvolumes", "Subvolumes and snapshots, which commonly hold unexpected space.",
        argv=("btrfs", "subvolume", "list", PATH_TOKEN), path_mode="optional", default_path="/",
        requires="btrfs", needs_root=True,
    ),
    "zfs_pools": DiskCommand("ZFS pools", "ZFS pool capacity and health.", argv=("zpool", "list"), requires="zpool"),
    "zfs_pool_status": DiskCommand("ZFS pool status", "ZFS pool device status and errors.", argv=("zpool", "status"), requires="zpool"),
    "zfs_datasets": DiskCommand("ZFS datasets", "ZFS datasets, snapshots and their space usage.", argv=("zfs", "list"), requires="zfs"),
    "encrypted_devices": DiskCommand(
        "Encrypted devices", "LUKS/dm-crypt mapped devices.",
        argv=("dmsetup", "ls", "--target", "crypt"), requires="dmsetup", needs_root=True,
    ),
    # ---- Health and errors ----
    "smart_health": DiskCommand(
        "Drive health (SMART)", "Overall SMART pass/fail for a drive. Requires a device such as /dev/sda.",
        argv=("smartctl", "-H", PATH_TOKEN), path_mode="required", requires="smartctl", needs_root=True,
    ),
    "smart_attributes": DiskCommand(
        "SMART attributes", "Detailed SMART attributes including reallocated sectors and wear. Requires a device.",
        argv=("smartctl", "-A", PATH_TOKEN), path_mode="required", requires="smartctl", needs_root=True,
    ),
    "smart_info": DiskCommand(
        "Drive information", "Model, firmware and capacity from SMART. Requires a device.",
        argv=("smartctl", "-i", PATH_TOKEN), path_mode="required", requires="smartctl", needs_root=True,
    ),
    "kernel_disk_errors": DiskCommand(
        "Kernel disk errors", "Recent kernel-level errors, which surface failing disks and filesystem faults.",
        argv=("journalctl", "-k", "-p", "err", "-n", "50", "--no-pager"), requires="journalctl",
    ),
    "io_error_log": DiskCommand(
        "I/O error log", "Kernel log entries mentioning I/O errors specifically.",
        argv=("journalctl", "-k", "--grep", "I/O error", "-n", "50", "--no-pager"), requires="journalctl",
    ),
    "fsck_dryrun": DiskCommand(
        "Filesystem check (dry run)", "Reports what a filesystem check would do without changing anything. Requires a device.",
        argv=("fsck", "-N", PATH_TOKEN), path_mode="required", requires="fsck",
    ),
    # ---- Performance ----
    "io_stats": DiskCommand(
        "I/O statistics", "Per-device throughput, latency and utilisation.",
        argv=("iostat", "-x", "1", "2"), requires="iostat", timeout=30,
    ),
    "disk_stats": DiskCommand("Raw disk statistics", "Kernel's cumulative per-device I/O counters.", kind="file", file_path="/proc/diskstats"),
    "io_pressure": DiskCommand("I/O pressure", "How much tasks are stalling on I/O.", kind="file", file_path="/proc/pressure/io"),
    # ---- Package and application storage ----
    "docker_usage": DiskCommand("Docker disk usage", "Docker images, containers, volumes and build cache.", argv=("docker", "system", "df", "-v"), requires="docker", timeout=30),
    "podman_usage": DiskCommand("Podman disk usage", "Podman images, containers and volumes.", argv=("podman", "system", "df"), requires="podman", timeout=30),
    "journal_usage": DiskCommand("Journal size", "Total space used by the systemd journal.", argv=("journalctl", "--disk-usage"), requires="journalctl"),
    "cache_usage": DiskCommand("User cache", "Size of the user cache directory.", argv=("du", "-sh", PATH_TOKEN), path_mode="optional", default_path=os.path.join(_home(), ".cache"), timeout=30),
    "trash_usage": DiskCommand("Trash", "Size of the trash directory.", argv=("du", "-sh", PATH_TOKEN), path_mode="optional", default_path=os.path.join(_home(), ".local/share/Trash"), timeout=30),
    "apt_cache_usage": DiskCommand("APT cache", "Debian/Ubuntu package cache size.", argv=("du", "-sh", "/var/cache/apt"), timeout=30),
    "dnf_cache_usage": DiskCommand("DNF cache", "Fedora/RHEL package cache size.", argv=("du", "-sh", "/var/cache/dnf"), timeout=30),
    "pacman_cache_usage": DiskCommand("Pacman cache", "Arch package cache size.", argv=("du", "-sh", "/var/cache/pacman"), timeout=30),
    "snap_usage": DiskCommand("Snap storage", "Space used by snap packages.", argv=("du", "-sh", "/var/lib/snapd"), timeout=30),
    "snap_revisions": DiskCommand("Snap revisions", "Installed snaps including old revisions that can be pruned.", argv=("snap", "list", "--all"), requires="snap"),
    "flatpak_usage": DiskCommand("Flatpak apps", "Installed Flatpak applications and their sizes.", argv=("flatpak", "--columns=application,size", "list"), requires="flatpak"),
    "pip_cache_usage": DiskCommand("pip cache", "Python package cache size.", argv=("du", "-sh", PATH_TOKEN), path_mode="optional", default_path=os.path.join(_home(), ".cache/pip"), timeout=30),
    "npm_cache_usage": DiskCommand("npm cache", "Node package cache size.", argv=("du", "-sh", PATH_TOKEN), path_mode="optional", default_path=os.path.join(_home(), ".npm"), timeout=30),
    "coredumps": DiskCommand("Core dumps", "Space used by saved crash dumps.", argv=("du", "-sh", "/var/lib/systemd/coredump"), timeout=30),
    "installed_kernels": DiskCommand("Installed kernels", "Installed kernel packages, which accumulate and fill /boot.", argv=("dpkg-query", "-W", "-f=${Package} ${Installed-Size}\\n", "linux-image-*"), requires="dpkg-query"),
    # ---- Swap ----
    "swap_usage": DiskCommand("Swap", "Swap devices and how much is in use.", argv=("swapon", "--show"), requires="swapon"),
    "zram_usage": DiskCommand("zram", "Compressed RAM block devices.", argv=("zramctl",), requires="zramctl"),
    # ---- Quotas ----
    "quota_usage": DiskCommand("Disk quotas", "Per-user quota limits and usage, where quotas are enabled.", argv=("quota", "-s"), requires="quota"),
}


def command_label(command_id):
    entry = DISK_COMMANDS.get(command_id)
    return entry.label if entry else str(command_id)


def tool_schema_properties():
    """Returns {command_id: description}, used to build each provider's tool schema."""
    return {cid: entry.description for cid, entry in DISK_COMMANDS.items()}


def _human(num_bytes):
    value = float(num_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return f"{value:.1f}{unit}"
        value /= 1024


def validate_path(raw):
    """Returns (resolved_path, None) or (None, error_message). The path becomes one element of an
    argv list and never touches a shell, so this validates for usability, not injection."""
    if raw is None or str(raw).strip() == "":
        return None, "no path given"
    text = str(raw)
    if "\x00" in text:
        return None, "path contains a null byte"

    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        return None, f"path must be absolute, got '{text}'"

    try:
        resolved = candidate.resolve()
    except OSError as e:
        return None, f"could not resolve path '{text}': {e}"

    if not resolved.exists():
        return None, f"path does not exist: {resolved}"

    return str(resolved), None


def _postprocess_size_paths(output):
    """find prints bare paths; size them here and sort, so no shell pipe to sort/head is needed."""
    sized = []
    for line in output.splitlines():
        path = line.strip()
        if not path:
            continue
        try:
            sized.append((os.path.getsize(path), path))
        except OSError:
            continue

    if not sized:
        return "No files matched."

    sized.sort(reverse=True)
    return "\n".join(f"{_human(size)}\t{path}" for size, path in sized[:20])


def _postprocess_sort_du(output):
    """du without -h prints size-in-blocks then path; sort numerically and render human sizes."""
    rows = []
    for line in output.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]) * 1024, parts[1].strip()))
        except ValueError:
            continue

    if not rows:
        return output

    rows.sort(reverse=True)
    return "\n".join(f"{_human(size)}\t{path}" for size, path in rows[:25])


_POSTPROCESSORS = {"size_paths": _postprocess_size_paths, "sort_du": _postprocess_sort_du}

_PERMISSION_MARKERS = ("permission denied", "must be root", "operation not permitted", "are you root")


def execute_disk_command(command_id, path=None):
    """Runs the allow-listed observation for command_id and returns its output as text. Never raises:
    an unknown id, a bad path, a missing binary, a permission problem or a timeout all return a short
    explanatory string, so the caller always has something to reason about."""
    entry = DISK_COMMANDS.get(command_id)
    if entry is None:
        return f"Error: unknown command '{command_id}'. Valid commands: {', '.join(DISK_COMMANDS)}."

    resolved_path = None
    if entry.path_mode != "none":
        if path:
            resolved_path, error = validate_path(path)
            if error:
                return f"Error: {error}"
        elif entry.path_mode == "required":
            return (
                f"{entry.label} needs a target (for example a device such as /dev/sda). "
                "Run block_devices or disk_hardware first to find the right one, then call this again "
                "with that value as the path."
            )
        else:
            resolved_path = entry.default_path or None

    if entry.kind == "file":
        try:
            return Path(entry.file_path).read_text().strip()[:MAX_OUTPUT_CHARS] or f"{entry.file_path} is empty."
        except FileNotFoundError:
            return f"{entry.file_path} does not exist on this system."
        except PermissionError:
            return f"Reading {entry.file_path} requires elevated permissions."
        except OSError as e:
            return f"Error reading {entry.file_path}: {e}"

    if entry.requires and shutil.which(entry.requires) is None:
        return f"{entry.requires} is not installed on this system, so {entry.label.lower()} is unavailable."

    argv = []
    for token in entry.argv:
        if token == PATH_TOKEN:
            if resolved_path:
                argv.append(resolved_path)
        else:
            argv.append(token)

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=entry.timeout)
    except subprocess.TimeoutExpired:
        return f"{entry.label} timed out after {entry.timeout}s."
    except OSError as e:
        logger.warning(f"{entry.label} ({' '.join(argv)}) failed: {e}")
        return f"Error running {entry.label}: {e}"

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        combined = f"{stdout}\n{stderr}".strip().lower()
        if entry.needs_root and any(marker in combined for marker in _PERMISSION_MARKERS):
            return (
                f"{entry.label} requires elevated permissions, so it could not be read. "
                "Running Opsy with sudo would allow this check."
            )
        if not stdout:
            return f"{entry.label} failed: {stderr or f'exit code {result.returncode}'}"

    if entry.postprocess and stdout:
        stdout = _POSTPROCESSORS[entry.postprocess](stdout)

    if not stdout:
        return f"{entry.label} returned no output."

    return stdout[:MAX_OUTPUT_CHARS]
