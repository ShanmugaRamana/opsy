from . import collector


def _memory_capacity_insight(ram):
    if ram is None:
        return {
            "id": "memory_capacity",
            "title": "Memory Capacity",
            "detail": "RAM stats are unavailable, so we can't assess memory capacity right now.",
            "severity": "unknown",
        }

    total = ram["total_gb"]
    if total < 8:
        detail = f"{total} GB of RAM is on the lower end — expect limited headroom for memory-intensive workloads."
    elif total < 16:
        detail = f"{total} GB of RAM offers moderate headroom for memory-intensive workloads."
    elif total < 32:
        detail = f"{total} GB of RAM offers ample headroom for memory-intensive workloads."
    else:
        detail = f"{total} GB of RAM offers substantial headroom, even for demanding workloads."

    return {
        "id": "memory_capacity",
        "title": "Memory Capacity",
        "detail": detail,
        "severity": "good",
    }


def _acceleration_insight(gpu, cpu_cores):
    if gpu is None:
        return {
            "id": "acceleration",
            "title": "GPU Detection",
            "detail": "GPU detection is unavailable, so we can't tell if hardware acceleration is available.",
            "severity": "unknown",
        }

    if gpu["dedicated"]:
        return {
            "id": "acceleration",
            "title": "GPU Acceleration",
            "detail": f"A dedicated GPU ({gpu['model']}) was detected, enabling hardware acceleration.",
            "severity": "good",
        }

    cores_text = f"{cpu_cores} CPU cores" if cpu_cores is not None else "the CPU"
    return {
        "id": "acceleration",
        "title": "No Dedicated GPU",
        "detail": f"No dedicated GPU detected — this machine relies on {cores_text} for compute.",
        "severity": "info",
    }


def _storage_insight(storage):
    if storage is None:
        return {
            "id": "storage",
            "title": "Storage",
            "detail": "Storage stats are unavailable, so we can't assess free disk space.",
            "severity": "unknown",
        }

    free = storage["free_gb"]
    if free < 10:
        detail = f"Only {free} GB free — disk space is running low."
        severity = "warn"
    else:
        detail = f"{free} GB free — plenty of headroom on disk."
        severity = "good"

    return {"id": "storage", "title": "Storage Headroom", "detail": detail, "severity": severity}


def _memory_pressure_insight(ram):
    if ram is None:
        return None

    total = ram["total_gb"]
    used = ram["used_gb"]
    if total <= 0:
        return None

    if (used / total) > 0.85:
        return {
            "id": "memory_pressure",
            "title": "Memory Pressure",
            "detail": "Memory is nearly full — close other applications to free up headroom.",
            "severity": "warn",
        }
    return None


def build_insights():
    ram = collector.get_ram()
    storage = collector.get_storage()
    gpu = collector.get_gpu()
    cpu_cores = collector.get_cpu_cores()

    insights = [
        _memory_capacity_insight(ram),
        _acceleration_insight(gpu, cpu_cores),
        _storage_insight(storage),
    ]

    memory_pressure = _memory_pressure_insight(ram)
    if memory_pressure is not None:
        insights.append(memory_pressure)

    return insights
