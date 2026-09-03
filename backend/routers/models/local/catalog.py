# Curated catalog of local (Ollama) models. Not a live sync from Ollama's library - a hand-picked
# ladder sized to real machines, replacing the eight hardcoded mock cards the setup page shipped with.
#
# MAX_PARAMS_B is a hard product rule, not a tuning knob: Opsy never recommends or lists a local model
# above 15B parameters, regardless of how much RAM/VRAM a machine has. `local/recommend.py` filters the
# catalog against it, and this module asserts every entry respects it, so a future addition can't
# silently break the rule.

MAX_PARAMS_B = 15.0

BACKEND = "ollama"

# key -> catalog entry. `tag` is the exact Ollama pull tag. `size_gb` is an estimate used only until a
# model is actually downloaded, at which point the measured byte count replaces it in `local_models`.
LOCAL_MODEL_CATALOG = {
    "qwen3-1.7b": {
        "tag": "qwen3:1.7b",
        "display_name": "Qwen3 1.7B",
        "params_b": 1.7,
        "quantization": "Q4_K_M",
        "size_gb": 1.4,
        "tool_calling": "limited",
    },
    "llama-3.2-3b": {
        "tag": "llama3.2:3b",
        "display_name": "Llama 3.2 3B",
        "params_b": 3.0,
        "quantization": "Q4_K_M",
        "size_gb": 2.0,
        "tool_calling": "limited",
    },
    "qwen3-4b": {
        "tag": "qwen3:4b",
        "display_name": "Qwen3 4B",
        "params_b": 4.0,
        "quantization": "Q4_K_M",
        "size_gb": 2.6,
        "tool_calling": "good",
    },
    "mistral-7b": {
        "tag": "mistral:7b",
        "display_name": "Mistral 7B",
        "params_b": 7.0,
        "quantization": "Q4_K_M",
        "size_gb": 4.4,
        "tool_calling": "good",
    },
    "qwen3-8b": {
        "tag": "qwen3:8b",
        "display_name": "Qwen3 8B",
        "params_b": 8.0,
        "quantization": "Q4_K_M",
        "size_gb": 5.2,
        "tool_calling": "strong",
    },
    "qwen3-14b": {
        "tag": "qwen3:14b",
        "display_name": "Qwen3 14B",
        "params_b": 14.0,
        "quantization": "Q4_K_M",
        "size_gb": 9.3,
        "tool_calling": "strong",
    },
}

for _key, _entry in LOCAL_MODEL_CATALOG.items():
    if _entry["params_b"] > MAX_PARAMS_B:
        raise ValueError(f"catalog entry {_key!r} is {_entry['params_b']}B, over the {MAX_PARAMS_B}B cap")


def get_entry(model_key):
    return LOCAL_MODEL_CATALOG.get(model_key)


def tag_for(model_key):
    entry = get_entry(model_key)
    return entry["tag"] if entry else None
