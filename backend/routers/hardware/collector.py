import logging
import re
import shutil
import subprocess

import psutil

logger = logging.getLogger("hardware.collector")

# GPU model substrings that indicate a virtualized/software adapter rather than real hardware.
_VIRTUAL_GPU_MARKERS = ("virtio", "qxl", "vmware", "virtualbox", "bochs", "cirrus", "llvmpipe", "swrast")


def get_os_name():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception as e:
        logger.warning(f"OS name unavailable: {e}")
    return None


def get_cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception as e:
        logger.warning(f"CPU model unavailable: {e}")
    return None


def get_cpu_cores():
    try:
        cores = psutil.cpu_count(logical=False)
        if cores is None:
            raise ValueError("psutil returned no physical core count")
        return cores
    except Exception as e:
        logger.warning(f"CPU core count unavailable: {e}")
        return None


def get_cpu_usage_percent():
    try:
        return psutil.cpu_percent(interval=0.5)
    except Exception as e:
        logger.warning(f"CPU usage unavailable: {e}")
        return None


def get_ram():
    try:
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "used_gb": round(mem.used / (1024 ** 3), 1),
        }
    except Exception as e:
        logger.warning(f"RAM stats unavailable: {e}")
        return None


def get_storage():
    try:
        usage = psutil.disk_usage("/")
        return {
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "free_gb": round(usage.free / (1024 ** 3), 1),
        }
    except Exception as e:
        logger.warning(f"Storage stats unavailable: {e}")
        return None


def _get_gpu_model_and_vendor():
    """Returns (model_string, dedicated_bool) via lspci, or (None, None) if unavailable."""
    if not shutil.which("lspci"):
        logger.warning("GPU model unavailable: lspci not found")
        return None, None

    try:
        output = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5, check=True
        ).stdout
    except Exception as e:
        logger.warning(f"GPU model unavailable: lspci failed: {e}")
        return None, None

    for line in output.splitlines():
        if "VGA compatible controller" in line or "3D controller" in line:
            model = line.split(":", 2)[-1].strip()
            dedicated = not any(marker in model.lower() for marker in _VIRTUAL_GPU_MARKERS)
            return model, dedicated

    logger.warning("GPU model unavailable: no VGA/3D controller found in lspci output")
    return None, None


def _get_nvidia_usage_percent():
    if not shutil.which("nvidia-smi"):
        return None
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        return float(output.splitlines()[0])
    except Exception as e:
        logger.warning(f"GPU utilization unavailable: nvidia-smi failed: {e}")
        return None


def _get_amd_usage_percent():
    try:
        with open("/sys/class/drm/card0/device/gpu_busy_percent") as f:
            return float(f.read().strip())
    except Exception as e:
        logger.warning(f"GPU utilization unavailable: {e}")
        return None


def _get_nvidia_vram_gb():
    if not shutil.which("nvidia-smi"):
        return None
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        mib = float(output.splitlines()[0])
        return round(mib / 1024, 1)
    except Exception as e:
        logger.warning(f"GPU VRAM unavailable: nvidia-smi failed: {e}")
        return None


def _get_amd_vram_gb():
    try:
        with open("/sys/class/drm/card0/device/mem_info_vram_total") as f:
            return round(float(f.read().strip()) / (1024 ** 3), 1)
    except Exception as e:
        logger.warning(f"GPU VRAM unavailable: {e}")
        return None


def get_gpu():
    model, dedicated = _get_gpu_model_and_vendor()
    if model is None:
        return None

    usage_percent = None
    vram_gb = None
    model_lower = model.lower()
    if "nvidia" in model_lower:
        usage_percent = _get_nvidia_usage_percent()
        vram_gb = _get_nvidia_vram_gb()
    elif re.search(r"\b(amd|ati|radeon)\b", model_lower):
        usage_percent = _get_amd_usage_percent()
        vram_gb = _get_amd_vram_gb()
    else:
        logger.warning("GPU utilization unavailable: no counter for this vendor")
        logger.warning("GPU VRAM unavailable: no counter for this vendor")

    return {"model": model, "dedicated": dedicated, "usage_percent": usage_percent, "vram_gb": vram_gb}
