from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Loads a prompt's text from backend/prompts/<name>.txt. Prompt content lives here, in plain
    text files, not embedded as string literals in the modules that use them."""
    return (_PROMPTS_DIR / f"{name}.txt").read_text().strip() + "\n"
