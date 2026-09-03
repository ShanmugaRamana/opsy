"""Turns a hardware profile into a fit verdict per catalog entry.

Follows the same missing-data contract the hardware cards use (see
plans/setup-page-hardware-and-byok.md): an unmeasured input produces an honest "unknown" verdict,
never a guess. Recommending an 8B to a machine whose RAM we couldn't read would be exactly the
fabrication that contract exists to prevent.
"""
import logging

from .catalog import LOCAL_MODEL_CATALOG

logger = logging.getLogger("local-models")

# Weights plus KV cache and runtime overhead - a Q4_K_M model needs meaningfully more than its file
# size to actually run.
_OVERHEAD_FACTOR = 1.25
_OVERHEAD_FLAT_GB = 1.0

# Reserved so the OS and the rest of the system aren't pushed into swap - the difference between
# "runs" and "the whole machine freezes".
_CPU_RAM_RESERVE_GB = 3.0

# Free disk must exceed the download size by this factor - the model file plus a safety margin.
_DISK_HEADROOM_FACTOR = 1.15

FIT_RECOMMENDED = "recommended"
FIT_POSSIBLE = "possible"
FIT_TOO_LARGE = "too_large"
FIT_NO_DISK_SPACE = "no_disk_space"
FIT_UNKNOWN = "unknown"


def _usable_memory_gb(profile):
    gpu = profile.get("gpu")
    if gpu and gpu.get("dedicated") and gpu.get("vram_gb") is not None:
        return gpu["vram_gb"]

    ram = profile.get("ram") or {}
    total = ram.get("total_gb")
    if total is not None:
        return max(total - _CPU_RAM_RESERVE_GB, 0.0)

    return None


def _need_gb(size_gb):
    return size_gb * _OVERHEAD_FACTOR + _OVERHEAD_FLAT_GB


def build_recommendations(profile):
    """Returns a list of dicts, one per catalog entry, each carrying `model_key`, the catalog fields,
    `fit`, and a human `reason`. Exactly one entry is `recommended` when the hardware supports any."""
    usable_gb = _usable_memory_gb(profile)
    free_gb = (profile.get("storage") or {}).get("free_gb")

    if usable_gb is None:
        logger.info("local-models - usable memory unknown, all entries marked unknown")

    results = []
    fitting = []

    for model_key, entry in LOCAL_MODEL_CATALOG.items():
        size_gb = entry["size_gb"]
        row = {
            "model_key": model_key,
            "tag": entry["tag"],
            "display_name": entry["display_name"],
            "params_b": entry["params_b"],
            "quantization": entry["quantization"],
            "size_gb": size_gb,
            "tool_calling": entry["tool_calling"],
        }

        if usable_gb is None:
            row["fit"] = FIT_UNKNOWN
            row["reason"] = "We couldn't measure your memory, so we can't tell you what fits."
            results.append(row)
            continue

        need_gb = _need_gb(size_gb)
        if need_gb > usable_gb:
            row["fit"] = FIT_TOO_LARGE
            row["reason"] = f"Needs ~{need_gb:.1f} GB of memory; you have ~{usable_gb:.1f} GB usable."
            results.append(row)
            continue

        if free_gb is not None and free_gb < size_gb * _DISK_HEADROOM_FACTOR:
            row["fit"] = FIT_NO_DISK_SPACE
            row["reason"] = f"Needs {size_gb * _DISK_HEADROOM_FACTOR:.1f} GB free; {free_gb:.1f} GB available."
            results.append(row)
            continue

        row["fit"] = FIT_POSSIBLE
        row["reason"] = None
        results.append(row)
        fitting.append(row)

    if fitting:
        best = max(fitting, key=lambda r: r["params_b"])
        best["fit"] = FIT_RECOMMENDED
        source = "VRAM" if (profile.get("gpu") or {}).get("dedicated") else "RAM"
        best["reason"] = f"Recommended for your {usable_gb:.1f} GB of usable {source}."
        logger.info(f"local-models - usable={usable_gb:.1f}GB ({source.lower()}) -> recommended {best['model_key']}")

    return results
