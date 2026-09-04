"""Turns a hardware profile into the one catalog category that machine should be offered.

Two contracts shape this module.

The first is the missing-data contract the hardware cards follow (see
plans/setup-page-hardware-and-byok.md): an unmeasured input produces an honest "we don't know", never
a guess. Recommending an 8B to a machine whose RAM we couldn't read would be exactly the fabrication
that contract exists to prevent.

The second is that **everything this module returns is downloadable**. There is no "too large" or
"not enough disk" verdict for the page to render as a muted card with a dead button - an entry that
does not fit is excluded here, with the reason logged, and never reaches the client. Category
membership does most of that work already (every model in a category fits that category's floor, per
catalog.py), so the filters below are the backstops for the two cases membership cannot cover: a
machine below the smallest category's floor, and a full disk.
"""
import logging

from .catalog import CATEGORIES, CATEGORY_ORDER, entries_in_category, need_gb

logger = logging.getLogger("local-models")

# Reserved so the OS and the rest of the system aren't pushed into swap - the difference between
# "runs" and "the whole machine freezes".
_CPU_RAM_RESERVE_GB = 3.0

# Free disk must exceed the download size by this factor - the model file plus a safety margin.
_DISK_HEADROOM_FACTOR = 1.15

FIT_RECOMMENDED = "recommended"
FIT_POSSIBLE = "possible"

# Exclusion reasons. These name why an entry was dropped in the log line; unlike the verdicts they
# replace, they can no longer appear in a response.
EXCLUDED_TOO_LARGE = "too_large"
EXCLUDED_NO_DISK_SPACE = "no_disk_space"


def _usable_memory_gb(profile):
    gpu = profile.get("gpu")
    if gpu and gpu.get("dedicated") and gpu.get("vram_gb") is not None:
        return gpu["vram_gb"]

    ram = profile.get("ram") or {}
    total = ram.get("total_gb")
    if total is not None:
        return max(total - _CPU_RAM_RESERVE_GB, 0.0)

    return None


def category_for(usable_gb):
    """The category key whose band contains `usable_gb`, or None if we couldn't measure memory. The
    last band is open-ended, so any machine with a known memory figure lands somewhere."""
    if usable_gb is None:
        return None

    for key in CATEGORY_ORDER:
        band = CATEGORIES[key]
        if usable_gb < band["min_usable_gb"]:
            continue
        if band["max_usable_gb"] is None or usable_gb < band["max_usable_gb"]:
            return key

    return CATEGORY_ORDER[-1]


def _row_from(entry):
    return {
        "model_key": entry["model_key"],
        "tag": entry["tag"],
        "display_name": entry["display_name"],
        "category": entry["category"],
        "params_b": entry["params_b"],
        "quantization": entry["quantization"],
        "size_gb": entry["size_gb"],
        "tool_calling": entry["tool_calling"],
        "streams_tool_calls": entry["streams_tool_calls"],
    }


def build_recommendations(profile):
    """Returns `{category, models, note}`.

    `category` is None only when memory could not be measured. Every entry in `models` is one this
    machine can run and has the disk space for, so the page can render all of them with an enabled
    Download button. `note` carries an honest sentence whenever the list is shorter than the
    category - hiding a model with no explanation would be worse than the muted card it replaces.
    """
    usable_gb = _usable_memory_gb(profile)
    free_gb = (profile.get("storage") or {}).get("free_gb")

    if usable_gb is None:
        logger.info("local-models - usable memory unknown, recommending nothing")
        return {
            "category": None,
            "models": [],
            "note": "We couldn't measure your memory, so we can't tell you which models will run.",
        }

    source = "VRAM" if (profile.get("gpu") or {}).get("dedicated") else "RAM"
    category_key = category_for(usable_gb)
    band = CATEGORIES[category_key]

    models = []
    excluded_too_large = 0
    largest_excluded_for_disk = None

    for entry in entries_in_category(category_key):
        entry_need = need_gb(entry["size_gb"])

        # Only reachable below the smallest category's floor - a machine with less usable memory than
        # even `lightweight` assumes. Everywhere else, catalog.py's floor assertion has already
        # guaranteed this passes.
        if entry_need > usable_gb:
            excluded_too_large += 1
            logger.info(
                f"local-models - excluding {entry['model_key']} ({EXCLUDED_TOO_LARGE}): "
                f"needs ~{entry_need:.1f} GB, {usable_gb:.1f} GB usable"
            )
            continue

        required_free_gb = entry["size_gb"] * _DISK_HEADROOM_FACTOR
        if free_gb is not None and free_gb < required_free_gb:
            largest_excluded_for_disk = max(largest_excluded_for_disk or 0.0, required_free_gb)
            logger.info(
                f"local-models - excluding {entry['model_key']} ({EXCLUDED_NO_DISK_SPACE}): "
                f"needs {required_free_gb:.1f} GB free, {free_gb:.1f} GB available"
            )
            continue

        models.append(_row_from(entry))

    for index, row in enumerate(models):
        row["fit"] = FIT_RECOMMENDED if index == 0 else FIT_POSSIBLE

    note = _build_note(
        models=models,
        usable_gb=usable_gb,
        free_gb=free_gb,
        excluded_too_large=excluded_too_large,
        largest_excluded_for_disk=largest_excluded_for_disk,
    )

    logger.info(
        f"local-models - usable={usable_gb:.1f}GB ({source.lower()}) -> category {category_key}, "
        f"{len(models)} of 4 models offered"
    )

    return {
        "category": {
            "key": category_key,
            "label": band["label"],
            "summary": band["summary"],
            "blurb": f"Sized for your {usable_gb:.1f} GB of usable {source}.",
            "usable_gb": round(usable_gb, 1),
            "source": source,
        },
        "models": models,
        "note": note,
    }


def _build_note(*, models, usable_gb, free_gb, excluded_too_large, largest_excluded_for_disk):
    if not models:
        if largest_excluded_for_disk is not None:
            return (
                f"You have {free_gb:.1f} GB of free disk space. The smallest model we'd offer this "
                "machine needs more than that - free some space and this list will fill in."
            )
        return (
            f"We measured {usable_gb:.1f} GB of usable memory, which is below what even our smallest "
            "model needs to run. A cloud provider on the other tab will work better here."
        )

    if largest_excluded_for_disk is not None:
        return (
            f"Some larger models are hidden: you have {free_gb:.1f} GB free and they need up to "
            f"{largest_excluded_for_disk:.1f} GB."
        )

    if excluded_too_large:
        return "Some larger models are hidden because this machine doesn't have the memory for them."

    return None
