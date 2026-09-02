# Curated allow-list of models per provider. Not a live sync from any provider's /models
# endpoint — this is our own catalog, replaced into the `models` table whenever that
# provider's key is (re-)verified.
#
# Each entry is (model_id, display_name). model_id is the API-facing identifier;
# display_name is what the UI shows.

PROVIDER_CATALOG = {
    "groq": [
        ("openai/gpt-oss-120b", "GPT OSS 120B"),
        ("openai/gpt-oss-20b", "GPT OSS 20B"),
        ("qwen/qwen3.6-27b", "Qwen 3.6 27B"),
        ("qwen/qwen3.8-27b", "Qwen 3.8 27B"),
    ],
    "anthropic": [
        ("claude-opus-5", "Claude Opus 5"),
        ("claude-sonnet-5", "Claude Sonnet 5"),
    ],
    "openai": [
        ("gpt-5", "GPT-5"),
        ("gpt-5-mini", "GPT-5 mini"),
        ("openai/gpt-oss-120b", "GPT OSS 120B"),
        ("openai/gpt-oss-20b", "GPT OSS 20B"),
    ],
    "gemini": [
        ("gemini-3.7-flash", "Gemini 3.7 Flash"),
        ("gemini-3.5-flash", "Gemini 3.5 Flash"),
        ("gemini-3.1-pro", "Gemini 3.1 Pro"),
        ("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite"),
    ],
}
