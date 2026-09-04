from prompts import load_prompt

# The orchestrator itself only names a session now. Answering is the base agent's job, and its prompt
# lives with it in agents/base/, the same way each specialist's does.
SESSION_TITLE_SYSTEM_PROMPT = load_prompt("session_title")
