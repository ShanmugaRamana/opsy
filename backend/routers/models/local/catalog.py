# Curated catalog of local (Ollama) models. Not a live sync from Ollama's library - a hand-picked
# ladder sized to real machines, split into four hardware categories of four models each.
#
# The setup page shows exactly one category: the one matching the machine it is running on. That is
# why every rule below is about a *category* being internally consistent rather than the catalog as a
# whole, and why `recommend.py` never has to render a model it then has to explain away.
#
# Four rules are enforced at import, not left to whoever edits the table next:
#
# MAX_PARAMS_B is a hard product rule, not a tuning knob: Opsy never recommends or lists a local model
# above 15B parameters, regardless of how much RAM/VRAM a machine has. This is why the higher
# categories climb the *quantization* ladder (Q4_K_M -> Q8_0 -> FP16) instead of the parameter ladder:
# a 32 GB machine cannot be offered a bigger model than a 16 GB one, so it is offered a better-fidelity
# build of the same class of model instead. Q4_K_M is a lossy 4-bit quantization; Q8_0 is very nearly
# lossless. That is a real upgrade and honest copy, which "30B" would not be under this cap.
#
# MODELS_PER_CATEGORY keeps each category a short, considered list rather than a long one to scroll -
# four well-spaced options, not a model per possible machine.
#
# `floor_gb` is what makes "everything the page shows is usable" true rather than aspirational: it is
# the memory of the *weakest* machine in a category's band, and every member must fit inside it. So the
# worst machine in a band can still run the largest model offered to it.
#
# `streams_tool_calls` is the rule the Llama note below used to express only as prose. Opsy drives
# every provider through one streaming tool loop (see plans/local-models-recommend-download-and-wiring.md),
# so a model that cannot emit tool_calls under stream=true does not belong here at all.

MAX_PARAMS_B = 15.0
MODELS_PER_CATEGORY = 4

BACKEND = "ollama"

# Weights plus KV cache and runtime overhead - a quantized model needs meaningfully more memory than
# its file size to actually run. Lives here rather than in recommend.py because the import-time floor
# assertion and the recommender must agree on one formula.
_OVERHEAD_FACTOR = 1.25
_OVERHEAD_FLAT_GB = 1.0


def need_gb(size_gb):
    """Memory a model actually needs to run, from its download size."""
    return size_gb * _OVERHEAD_FACTOR + _OVERHEAD_FLAT_GB


# Ordered smallest machine first. `max_usable_gb` is exclusive; the last band is open-ended.
CATEGORY_ORDER = ("lightweight", "balanced", "performance", "high_end")

CATEGORIES = {
    "lightweight": {
        "label": "Lightweight",
        "min_usable_gb": 0.0,
        "max_usable_gb": 8.0,
        "floor_gb": 4.0,
        "summary": "Small models that stay responsive on CPU inference and modest memory.",
    },
    "balanced": {
        "label": "Balanced",
        "min_usable_gb": 8.0,
        "max_usable_gb": 14.0,
        "floor_gb": 8.0,
        "summary": "The mainstream tier - 7B-8B models at Q4_K_M, comfortable on a 16 GB machine.",
    },
    "performance": {
        "label": "Performance",
        "min_usable_gb": 14.0,
        "max_usable_gb": 22.0,
        "floor_gb": 14.0,
        "summary": "14B models, and 8B models at near-lossless Q8_0 fidelity.",
    },
    "high_end": {
        "label": "High-end",
        "min_usable_gb": 22.0,
        "max_usable_gb": None,
        "floor_gb": 22.0,
        "summary": "The same model classes at Q8_0 and FP16 - the most fidelity the 15B cap allows.",
    },
}

# key -> catalog entry. `tag` is the exact Ollama pull tag. `size_gb` is an estimate used only until a
# model is actually downloaded, at which point the measured byte count replaces it in `local_models`.
# `tool_calling` is a quality note (how *well* a model uses tools); `streams_tool_calls` is the hard
# requirement (whether it can emit them at all while streaming).
LOCAL_MODEL_CATALOG = {
    # ---- lightweight: need_gb <= 4.0 ----
    "qwen3-0.6b": {
        "tag": "qwen3:0.6b",
        "display_name": "Qwen3 0.6B",
        "category": "lightweight",
        "params_b": 0.6,
        "quantization": "Q4_K_M",
        "size_gb": 0.5,
        "tool_calling": "limited",
        "streams_tool_calls": True,
    },
    "qwen3-1.7b": {
        "tag": "qwen3:1.7b",
        "display_name": "Qwen3 1.7B",
        "category": "lightweight",
        "params_b": 1.7,
        "quantization": "Q4_K_M",
        "size_gb": 1.4,
        "tool_calling": "limited",
        "streams_tool_calls": True,
    },
    # No Llama-family entries: Ollama's Llama chat templates only fill in tool_calls reliably with
    # stream=false, and every call in this app - the agents' tool loops (shared.ollama_round) and the
    # plain classify/title/chat path - is built around stream=true. A Llama model here would either
    # silently drop its tool calls mid-turn or need a special-cased non-streaming path, neither of
    # which is worth it. This is the worked example of what `streams_tool_calls` exists to exclude.
    "qwen2.5-3b": {
        "tag": "qwen2.5:3b",
        "display_name": "Qwen2.5 3B",
        "category": "lightweight",
        "params_b": 3.0,
        "quantization": "Q4_K_M",
        "size_gb": 1.9,
        "tool_calling": "limited",
        "streams_tool_calls": True,
    },
    "granite4.1-3b": {
        "tag": "granite4.1:3b",
        "display_name": "Granite 4.1 3B",
        "category": "lightweight",
        "params_b": 3.0,
        "quantization": "Q4_K_M",
        "size_gb": 2.1,
        "tool_calling": "good",
        "streams_tool_calls": True,
    },

    # ---- balanced: need_gb <= 8.0 ----
    "qwen3-4b": {
        "tag": "qwen3:4b",
        "display_name": "Qwen3 4B",
        "category": "balanced",
        "params_b": 4.0,
        "quantization": "Q4_K_M",
        "size_gb": 2.5,
        "tool_calling": "good",
        "streams_tool_calls": True,
    },
    "mistral-7b": {
        "tag": "mistral:7b",
        "display_name": "Mistral 7B",
        "category": "balanced",
        "params_b": 7.0,
        "quantization": "Q4_0",
        "size_gb": 4.4,
        "tool_calling": "good",
        "streams_tool_calls": True,
    },
    "qwen2.5-7b": {
        "tag": "qwen2.5:7b",
        "display_name": "Qwen2.5 7B",
        "category": "balanced",
        "params_b": 7.0,
        "quantization": "Q4_K_M",
        "size_gb": 4.7,
        "tool_calling": "good",
        "streams_tool_calls": True,
    },
    "qwen3-8b": {
        "tag": "qwen3:8b",
        "display_name": "Qwen3 8B",
        "category": "balanced",
        "params_b": 8.0,
        "quantization": "Q4_K_M",
        "size_gb": 5.2,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },

    # ---- performance: need_gb <= 14.0 ----
    "qwen3-8b-q8": {
        "tag": "qwen3:8b-q8_0",
        "display_name": "Qwen3 8B (Q8)",
        "category": "performance",
        "params_b": 8.0,
        "quantization": "Q8_0",
        "size_gb": 8.9,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },
    "qwen2.5-14b": {
        "tag": "qwen2.5:14b",
        "display_name": "Qwen2.5 14B",
        "category": "performance",
        "params_b": 14.0,
        "quantization": "Q4_K_M",
        "size_gb": 9.0,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },
    "qwen3-14b": {
        "tag": "qwen3:14b",
        "display_name": "Qwen3 14B",
        "category": "performance",
        "params_b": 14.0,
        "quantization": "Q4_K_M",
        "size_gb": 9.3,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },
    "granite4.1-8b-q8": {
        "tag": "granite4.1:8b-q8_0",
        "display_name": "Granite 4.1 8B (Q8)",
        "category": "performance",
        "params_b": 8.0,
        "quantization": "Q8_0",
        "size_gb": 9.3,
        "tool_calling": "good",
        "streams_tool_calls": True,
    },

    # ---- high_end: need_gb <= 22.0 ----
    "mistral-7b-fp16": {
        "tag": "mistral:7b-instruct-v0.3-fp16",
        "display_name": "Mistral 7B (FP16)",
        "category": "high_end",
        "params_b": 7.0,
        "quantization": "FP16",
        "size_gb": 14.0,
        "tool_calling": "good",
        "streams_tool_calls": True,
    },
    "qwen3-8b-fp16": {
        "tag": "qwen3:8b-fp16",
        "display_name": "Qwen3 8B (FP16)",
        "category": "high_end",
        "params_b": 8.0,
        "quantization": "FP16",
        "size_gb": 16.0,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },
    "qwen3-14b-q8": {
        "tag": "qwen3:14b-q8_0",
        "display_name": "Qwen3 14B (Q8)",
        "category": "high_end",
        "params_b": 14.0,
        "quantization": "Q8_0",
        "size_gb": 16.0,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },
    "qwen2.5-14b-q8": {
        "tag": "qwen2.5:14b-instruct-q8_0",
        "display_name": "Qwen2.5 14B (Q8)",
        "category": "high_end",
        "params_b": 14.0,
        "quantization": "Q8_0",
        "size_gb": 16.0,
        "tool_calling": "strong",
        "streams_tool_calls": True,
    },
}


def _validate_catalog():
    """Every product rule in this module's docstring, enforced at import so a future edit fails loudly
    at startup instead of shipping a card the machine cannot run."""
    counts = {key: 0 for key in CATEGORY_ORDER}

    for key, entry in LOCAL_MODEL_CATALOG.items():
        if entry["params_b"] > MAX_PARAMS_B:
            raise ValueError(f"catalog entry {key!r} is {entry['params_b']}B, over the {MAX_PARAMS_B}B cap")

        if not entry.get("streams_tool_calls"):
            raise ValueError(
                f"catalog entry {key!r} does not declare streams_tool_calls - Opsy drives every "
                "provider through one streaming tool loop, so a model that cannot emit tool_calls "
                "under stream=true has no place in the catalog"
            )

        category = entry.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"catalog entry {key!r} has unknown category {category!r}")
        counts[category] += 1

        floor_gb = CATEGORIES[category]["floor_gb"]
        entry_need = need_gb(entry["size_gb"])
        if entry_need > floor_gb:
            raise ValueError(
                f"catalog entry {key!r} needs ~{entry_need:.1f} GB but category {category!r} must be "
                f"runnable on {floor_gb:.1f} GB - the weakest machine in a band has to be able to run "
                "every model that band is offered"
            )

    for category, count in counts.items():
        if count != MODELS_PER_CATEGORY:
            raise ValueError(
                f"category {category!r} has {count} entries, expected exactly {MODELS_PER_CATEGORY} - "
                "each category is a short, considered list, not a model per possible machine"
            )


_validate_catalog()


def get_entry(model_key):
    return LOCAL_MODEL_CATALOG.get(model_key)


def tag_for(model_key):
    entry = get_entry(model_key)
    return entry["tag"] if entry else None


def entries_in_category(category):
    """Catalog entries for one category, each as a dict carrying its own `model_key`, largest first -
    the order the setup page renders them in."""
    rows = [
        {"model_key": key, **entry}
        for key, entry in LOCAL_MODEL_CATALOG.items()
        if entry["category"] == category
    ]
    # Parameter count breaks a size tie, so a 14B leads an 8B built at higher precision to the same
    # number of gigabytes.
    rows.sort(key=lambda r: (r["size_gb"], r["params_b"]), reverse=True)
    return rows
