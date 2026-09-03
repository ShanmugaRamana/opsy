"""Pieces every agent needs that carry no knowledge of any particular agent.

The per-provider tool loops deliberately stay in each agent's own `tool_clients.py`: the disk agent's
version is the reference implementation, and duplicating a loop is cheaper than a wrong abstraction
over four providers' streaming formats. What lives here is only what is genuinely neutral - text
helpers, the two forcing messages, and the ad-hoc command flow, which talks to `permissions` and the
command tool route and does not care which agent asked.

Moving these out changed no behaviour; the disk agent's loops call exactly what they called before.
"""
import json
import logging
import os
import re

import httpx

from routers.orchestrator import permissions
from routers.orchestrator.ratelimit import MAX_TRANSIENT_RETRIES, transient_delay, wait_before_transient_retry
from routers.orchestrator.tools.command.tool import validate_argv

logger = logging.getLogger("orchestrator.agents")

INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")

COMMAND_TOOL_NAME = "request_command"


def command_tool_description(primary_tool):
    """`primary_tool` is the agent's own allow-list tool, named so the model is pointed back at it
    rather than reaching for an approval it does not need."""
    return (
        "Ask the user's permission to run one read-only command that "
        f"{primary_tool} does not cover, then run it if they approve. Use this only for a genuine "
        f"gap - prefer {primary_tool} whenever one of its commands fits. There is no shell: give the "
        "command as an argv list. A pipe, redirect or command-substitution token (|, >, <, ;, &, or "
        "backticks) is refused outright, since there is nothing here to interpret it - request the "
        "raw output of one command and work with it yourself instead of trying to chain commands "
        "together. For a 'how many' question, set count_lines to true instead of trying to pipe into "
        "wc -l. The user sees the exact command and your reason before deciding, and may say no."
    )

ARGV_DESCRIPTION = (
    "The command as a list of arguments, e.g. [\"find\", \"/home\", \"-maxdepth\", \"2\", \"-type\", \"f\"]. "
    "No shell metacharacters: they are passed literally, not interpreted, and a pipe/redirect token "
    "is refused before the user is even asked."
)
REASON_DESCRIPTION = (
    "One sentence, shown to the user, saying what this command will reveal and why the built-in "
    "commands cannot answer it."
)
COUNT_LINES_DESCRIPTION = (
    "Set true to get back a count of matching lines instead of the raw output - the answer to a "
    "'how many' question, computed from the complete result rather than a possibly truncated "
    "listing. This is the replacement for piping into wc -l, which will not work."
)
COMMAND_DECLINED = "The user declined to run this command."


# ---- Forcing messages ----

def final_round_message(report_tag):
    """Sent on the final round, where the tool schema is withheld. Withholding the tools is invisible
    to the model - nothing in the conversation says the budget is gone - so without this it keeps
    narrating its next step and never writes the report. That is the exact failure this prevents."""
    return (
        "You have used all of your tool rounds and cannot run any more commands. Answer now, from "
        f"what you have already observed, with ONLY the <{report_tag}> XML and nothing else. If "
        "something could not be determined, say so in the explanation rather than asking to check "
        "further."
    )


def nudge_message(tool_name, report_tag):
    """Sent back when a round produces neither a tool call nor the final report - weaker models
    sometimes narrate their intent ("Let me check what is running...") and then just stop without
    following through. Without this, that narration would be taken as the final answer."""
    return (
        f"You did not call {tool_name} or provide your final answer. Either call the tool now for "
        "whatever you still need to check, or if you already have enough information, respond with "
        f"ONLY the <{report_tag}> XML and nothing else."
    )


def has_report(text, report_tag):
    return f"<{report_tag}" in (text or "").lower()


# ---- Narration / XML split ----

# Narration is the prose the model writes before its final answer; the answer itself is XML. The
# split is therefore at the first real tag, not at the first '<' - "less than 1 GB free" is prose a
# user wants to read, and cutting on the bare character silently truncated it.
_TAG_START_RE = re.compile(r"</?[A-Za-z]")


def narration_prefix_len(buffered, complete=False):
    """How much of `buffered` can safely be shown as narration.

    A chunk boundary can split a tag ('<disk_repo' + 'rt>'), so while the stream is still open a
    trailing '<' or '</' is held back until the next chunk decides whether it opens a tag. Once the
    round is complete there is nothing left to wait for and the remainder is prose."""
    match = _TAG_START_RE.search(buffered)
    if match:
        return match.start()
    if not complete:
        for fragment in ("</", "<"):
            if buffered.endswith(fragment):
                return len(buffered) - len(fragment)
    return len(buffered)


def narration_chunk(buffered, narrated, complete=False):
    """The slice of `buffered` not yet streamed, given `narrated` characters already sent."""
    limit = narration_prefix_len(buffered, complete)
    if limit <= narrated:
        return "", narrated
    return buffered[narrated:limit], limit


# ---- The ad-hoc command flow ----

def command_result(agent, label, output):
    return {
        "type": "tool_result",
        "agent": agent,
        "command": COMMAND_TOOL_NAME,
        "label": label,
        "path": None,
        "output": output,
    }


async def call_command_tool(request_id, argv, count_lines=False):
    """Runs an approved command over its real HTTP route, which re-checks the approval."""
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            response = await client.post(
                f"{INTERNAL_API_BASE}/linux/tools/command/run",
                json={"request_id": request_id, "argv": list(argv), "count_lines": bool(count_lines)},
            )
        if response.status_code == 403:
            return response.json().get("detail", "This command was not approved.")
        response.raise_for_status()
        return response.json()["output"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return f"Error running the approved command: {e}"


async def run_command_request(agent, argv, reason, count_lines=False):
    """Asks the user to approve one ad-hoc command, then runs it if they say yes.

    Nothing is executed before the user answers, and a refusal is reported to the model as a plain
    fact - it must say the command was declined rather than inventing what it would have shown."""
    argv = [str(token) for token in (argv or [])]
    count_lines = bool(count_lines)
    label = " ".join(argv) or "(no command)"

    # Checked before the user is prompted, so Opsy never asks permission for something it would
    # refuse to run anyway. This is also where a pipe/redirect token gets caught: the model gets an
    # actionable error back in the same round, rather than an approval round trip that ends in a
    # confusing shell-syntax error from the target binary.
    _, error = validate_argv(argv)
    if error:
        yield command_result(agent, label, f"That command cannot be run: {error}.")
        return

    request_id = permissions.create(argv, reason)
    yield {
        "type": "permission_request",
        "agent": agent,
        "request_id": request_id,
        "command": label,
        "reason": (reason or "").strip(),
        "count_lines": count_lines,
    }

    try:
        approved = await permissions.wait(request_id)
        yield {
            "type": "permission_resolved",
            "agent": agent,
            "request_id": request_id,
            "command": label,
            "approved": approved,
        }

        if not approved:
            yield command_result(agent, label, COMMAND_DECLINED)
            return

        yield {
            "type": "tool_call",
            "agent": agent,
            "command": COMMAND_TOOL_NAME,
            "label": label,
            "path": None,
        }
        output = await call_command_tool(request_id, argv, count_lines)
    finally:
        permissions.discard(request_id)

    yield command_result(agent, label, output)


# ---- request_command's tool schema, per provider ----

def anthropic_command_tool(primary_tool):
    return {
        "name": COMMAND_TOOL_NAME,
        "description": command_tool_description(primary_tool),
        "input_schema": {
            "type": "object",
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}, "description": ARGV_DESCRIPTION},
                "reason": {"type": "string", "description": REASON_DESCRIPTION},
                "count_lines": {"type": "boolean", "description": COUNT_LINES_DESCRIPTION},
            },
            "required": ["argv", "reason"],
        },
    }


def openai_command_tool(primary_tool):
    return {
        "type": "function",
        "function": {
            "name": COMMAND_TOOL_NAME,
            "description": command_tool_description(primary_tool),
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string"}, "description": ARGV_DESCRIPTION},
                    "reason": {"type": "string", "description": REASON_DESCRIPTION},
                    "count_lines": {"type": "boolean", "description": COUNT_LINES_DESCRIPTION},
                },
                "required": ["argv", "reason"],
            },
        },
    }


def ollama_command_tool(primary_tool):
    # Ollama's /api/chat accepts the same OpenAI-style function tool schema as the request payload -
    # only its *response* shape (streaming format, tool-call framing) differs, which is what
    # ollama_round below exists to parse. The request side needs no separate schema.
    return openai_command_tool(primary_tool)


def gemini_command_tool(primary_tool):
    return {
        "name": COMMAND_TOOL_NAME,
        "description": command_tool_description(primary_tool),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "argv": {"type": "ARRAY", "items": {"type": "STRING"}, "description": ARGV_DESCRIPTION},
                "reason": {"type": "STRING", "description": REASON_DESCRIPTION},
                "count_lines": {"type": "BOOLEAN", "description": COUNT_LINES_DESCRIPTION},
            },
            "required": ["argv", "reason"],
        },
    }


# ---- Ollama transport ----
#
# This is a real parser, not a thin wrapper over the OpenAI-compatible round above: Ollama's native
# /api/chat differs from the OpenAI dialect in every direction that matters - NDJSON lines instead of
# SSE `data:` frames, `message.content` / `message.tool_calls` instead of `choices[0].delta`, and tool
# call arguments arriving as a JSON *object* rather than a string fragment to reassemble. (Ollama's
# OpenAI-compatible /v1/chat/completions endpoint was deliberately not used here - it silently drops
# tool calls when streaming is enabled, which would break every agent's tool loop.)
#
# Kept here because it carries no knowledge of any particular agent - only the transport. Each agent's
# own `_run_ollama` loop (system prompt, report tag, tool dispatch, nudges, final round) stays in its
# own tool_clients.py, exactly like the OpenAI-compatible round does.
OLLAMA_CONTEXT_LENGTH = 16384


async def ollama_round(base_url, model_id, messages, tools, result, read_timeout=600.0):
    """Streams one round against Ollama's /api/chat. Fills `result` with `text` (the round's
    narration) and `tool_calls` (a list of {id, name, arguments}, `arguments` re-serialized as a JSON
    string so the rest of an agent's loop can `json.loads` it exactly like the OpenAI-shaped agents
    do), or sets `result["error"]` on failure.

    There is no 429 concept for a model running on this machine, so unlike the cloud rounds this only
    retries on genuine connection failures - a dropped connection or Ollama not yet finished loading
    the model into memory."""
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": True,
        "keep_alive": "10m",
        "options": {"num_ctx": OLLAMA_CONTEXT_LENGTH},
    }
    if tools:
        payload["tools"] = tools

    timeout = httpx.Timeout(connect=5.0, read=read_timeout, write=30.0, pool=5.0)

    for attempt in range(MAX_TRANSIENT_RETRIES + 1):
        buffered = ""
        narrated = 0
        tool_calls = []

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{base_url}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")
                        result["error"] = f"{response.status_code}: {body[:300]}"
                        return

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if chunk.get("error"):
                            result["error"] = chunk["error"]
                            return

                        message = chunk.get("message") or {}
                        text = message.get("content")
                        if text:
                            buffered += text
                            narration, narrated = narration_chunk(buffered, narrated)
                            if narration:
                                yield {"type": "thinking_delta", "text": narration}

                        for call in message.get("tool_calls") or []:
                            function = call.get("function") or {}
                            args = function.get("arguments")
                            args_str = args if isinstance(args, str) else json.dumps(args or {})
                            tool_calls.append({
                                "id": f"call_{len(tool_calls)}",
                                "name": function.get("name", ""),
                                "arguments": args_str,
                            })

                        if chunk.get("done"):
                            break
        except httpx.HTTPError as e:
            # Retrying a round that already streamed narration or collected tool calls would replay
            # them on the client, so only an untouched round can be replayed - same rule the
            # OpenAI-compatible round follows.
            if narrated or tool_calls or attempt >= MAX_TRANSIENT_RETRIES:
                result["error"] = str(e)
                return
            delay = transient_delay(attempt)
            yield {"type": "retrying", "retry_in": delay, "attempt": attempt + 1}
            await wait_before_transient_retry(delay, attempt, str(e)[:120])
            continue

        narration, narrated = narration_chunk(buffered, narrated, complete=True)
        if narration:
            yield {"type": "thinking_delta", "text": narration}

        result["text"] = buffered
        result["tool_calls"] = tool_calls
        return

    result.setdefault("error", "ollama retries exhausted without a response")
