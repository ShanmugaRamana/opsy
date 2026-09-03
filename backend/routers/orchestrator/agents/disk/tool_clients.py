import json
import logging
import os

import anthropic
import httpx

from routers.orchestrator.ratelimit import (
    MAX_RATE_LIMIT_RETRIES,
    is_rate_limited,
    retry_delay,
    space_calls,
    wait_before_retry,
)
from routers.orchestrator.schemas import CommandRun
from routers.orchestrator.tools.disk.tool import DISK_COMMANDS, command_label, tool_schema_properties

from .prompt import DISK_AGENT_SYSTEM_PROMPT
from .xml import parse_disk_report

logger = logging.getLogger("orchestrator.disk")

TOOL_NAME = "run_disk_command"
TOOL_DESCRIPTION = (
    "Run one read-only diagnostic command about disk or storage and return its output. "
    "Some commands accept a path (a directory, or a device such as /dev/sda)."
)
PATH_DESCRIPTION = (
    "Optional target for commands that accept one: an absolute directory path, or a device path for "
    "drive-health commands. Omit it to use the command's default."
)
MAX_TOOL_ROUNDS = 4
MAX_TOKENS = 16000
_HTTP_TIMEOUT = 120.0

# Sent back to the model when a round produces neither a tool call nor the final report - weaker
# models sometimes narrate their intent ("Let me check disk usage...") and then just stop without
# following through. Without this, that narration would be taken as the final answer.
NUDGE_MESSAGE = (
    "You did not call run_disk_command or provide your final answer. Either call the tool now for "
    "whatever you still need to check, or if you already have enough information, respond with ONLY "
    "the <disk_report> XML and nothing else."
)


def _has_report(text):
    return "<disk_report" in (text or "").lower()

INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")


def _command_enum_description():
    """Only the first sentence of each command's description. The full text is useful reading in the
    source, but this string ships on every round of every request, so the extra detail is a real
    token cost against a provider's per-minute budget."""
    parts = []
    for cid, description in tool_schema_properties().items():
        parts.append(f"{cid}: {description.split('. ')[0].rstrip('.')}")
    return "; ".join(parts)


async def _call_disk_tool(command_id, path=None):
    """Calls the disk tool over its real HTTP route (loopback) rather than the function directly.
    Never raises - any failure becomes an error string the agent can reason about."""
    try:
        params = {"path": path} if path else None
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.get(f"{INTERNAL_API_BASE}/linux/tools/disk/{command_id}", params=params)
        if response.status_code == 404:
            return response.json().get("detail", f"Unknown command '{command_id}'")
        response.raise_for_status()
        return response.json()["output"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return f"Error calling disk tool '{command_id}': {e}"


async def _run_tool(command_id, path=None):
    label = command_label(command_id)
    yield {"type": "tool_call", "agent": "disk", "command": command_id, "label": label, "path": path}
    output = await _call_disk_tool(command_id, path)
    yield {
        "type": "tool_result",
        "agent": "disk",
        "command": command_id,
        "label": label,
        "path": path,
        "output": output,
    }


def _final_event(disk_report, thinking, commands_run):
    return {
        "type": "final",
        "mode": "disk",
        "thinking": thinking.strip() or None,
        "disk_report": disk_report.model_dump(),
        "commands_run": [cr.model_dump() for cr in commands_run],
    }


def _narration_delta(buffered, delta):
    """Returns the part of `delta` that is still narration, given everything buffered before it.

    The final answer is XML and narration is prose, so narration ends at the first '<'. Cutting at
    that character rather than testing whole chunks matters because a chunk boundary can split a tag
    ('<disk_repo' + 'rt>'), which would otherwise leak into the thinking panel."""
    if "<" in buffered:
        return ""

    combined = buffered + delta
    index = combined.find("<")
    if index == -1:
        return delta
    return combined[len(buffered):index]


# ---- Anthropic ----

def _anthropic_tool_schema():
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": list(DISK_COMMANDS.keys()),
                    "description": _command_enum_description(),
                },
                "path": {"type": "string", "description": PATH_DESCRIPTION},
            },
            "required": ["command"],
        },
    }


async def _anthropic_round(client, model_id, messages, tools, result):
    kwargs = {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "system": DISK_AGENT_SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        buffered = ""
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                        narration = _narration_delta(buffered, event.delta.text)
                        buffered += event.delta.text
                        if narration:
                            yield {"type": "thinking_delta", "text": narration}
                result["message"] = await stream.get_final_message()
            return
        except anthropic.RateLimitError as e:
            if attempt >= MAX_RATE_LIMIT_RETRIES:
                result["error"] = str(e)
                result["rate_limited"] = True
                return
            headers = getattr(getattr(e, "response", None), "headers", None)
            delay = retry_delay(headers, str(e), attempt)
            yield {"type": "rate_limited", "retry_in": delay, "attempt": attempt + 1}
            await wait_before_retry(delay, attempt)
        except anthropic.APIError as e:
            result["error"] = str(e)
            return


async def _run_anthropic(api_key, model_id, message):
    client = anthropic.AsyncAnthropic(api_key=api_key)
    tools = [_anthropic_tool_schema()]
    messages = [{"role": "user", "content": message}]
    commands_run = []
    narration = ""
    final_text = ""

    for round_index in range(MAX_TOOL_ROUNDS + 1):
        # The extra final round runs without tools, forcing an answer once the cap is reached.
        round_tools = tools if round_index < MAX_TOOL_ROUNDS else None

        result = {}
        async for event in _anthropic_round(client, model_id, messages, round_tools, result):
            if event["type"] == "thinking_delta":
                narration += event["text"]
            yield event

        if "error" in result:
            yield {
                "type": "error",
                "detail": result["error"],
                "status": 429 if result.get("rate_limited") else 502,
            }
            return

        response = result["message"]
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text = "".join(b.text for b in response.content if b.type == "text")
        if text.strip():
            final_text = text

        if not tool_use_blocks:
            if _has_report(text) or round_index == MAX_TOOL_ROUNDS:
                final_text = text
                break
            # Narrated but never called the tool or gave a report - nudge it and try again.
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            continue

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            command_id = (block.input or {}).get("command")
            path = (block.input or {}).get("path")
            output = None
            async for event in _run_tool(command_id, path):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            commands_run.append(
                CommandRun(command=str(command_id), label=command_label(command_id), path=path, output=output)
            )
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": tool_results})

    yield _final_event(parse_disk_report(final_text), narration, commands_run)


# ---- OpenAI / Groq (OpenAI-compatible) ----

def _openai_tool_schema():
    return [{
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": list(DISK_COMMANDS.keys()),
                        "description": _command_enum_description(),
                    },
                    "path": {"type": "string", "description": PATH_DESCRIPTION},
                },
                "required": ["command"],
            },
        },
    }]


async def _openai_round(base_url, api_key, model_id, messages, tools, result):
    payload = {"model": model_id, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        retry_after = None
        buffered = ""
        tool_calls = {}

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                async with client.stream(
                    "POST", base_url, headers={"Authorization": f"Bearer {api_key}"}, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")
                        if is_rate_limited(response.status_code) and attempt < MAX_RATE_LIMIT_RETRIES:
                            retry_after = retry_delay(response.headers, body, attempt)
                        else:
                            result["error"] = f"{response.status_code}: {body[:300]}"
                            result["rate_limited"] = is_rate_limited(response.status_code)
                            return
                    else:
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:"):].strip()
                            if not data or data == "[DONE]":
                                continue

                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue

                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}

                            text = delta.get("content")
                            if text:
                                narration = _narration_delta(buffered, text)
                                buffered += text
                                if narration:
                                    yield {"type": "thinking_delta", "text": narration}

                            # Streamed tool calls arrive as fragments: the id and name land early,
                            # while `arguments` builds up across chunks and is only parseable once
                            # the round ends.
                            for fragment in delta.get("tool_calls") or []:
                                slot = tool_calls.setdefault(
                                    fragment.get("index", 0), {"id": "", "name": "", "arguments": ""}
                                )
                                if fragment.get("id"):
                                    slot["id"] = fragment["id"]
                                function = fragment.get("function") or {}
                                if function.get("name"):
                                    slot["name"] = function["name"]
                                if function.get("arguments"):
                                    slot["arguments"] += function["arguments"]
        except httpx.HTTPError as e:
            result["error"] = str(e)
            return

        if retry_after is not None:
            yield {"type": "rate_limited", "retry_in": retry_after, "attempt": attempt + 1}
            await wait_before_retry(retry_after, attempt)
            continue

        result["text"] = buffered
        result["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return


async def _run_openai_compatible(base_url, api_key, model_id, message):
    tools = _openai_tool_schema()
    messages = [
        {"role": "system", "content": DISK_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    commands_run = []
    narration = ""
    final_text = ""

    for round_index in range(MAX_TOOL_ROUNDS + 1):
        round_tools = tools if round_index < MAX_TOOL_ROUNDS else None

        result = {}
        async for event in _openai_round(base_url, api_key, model_id, messages, round_tools, result):
            if event["type"] == "thinking_delta":
                narration += event["text"]
            yield event

        if "error" in result:
            yield {
                "type": "error",
                "detail": result["error"],
                "status": 429 if result.get("rate_limited") else 502,
            }
            return

        if (result.get("text") or "").strip():
            final_text = result["text"]

        calls = result.get("tool_calls") or []
        if not calls:
            if _has_report(result.get("text")) or round_index == MAX_TOOL_ROUNDS:
                final_text = result.get("text", "") or final_text
                break
            # Narrated but never called the tool or gave a report - nudge it and try again.
            messages.append({"role": "assistant", "content": result.get("text") or ""})
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            continue

        messages.append({
            "role": "assistant",
            "content": result.get("text") or None,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                }
                for call in calls
            ],
        })

        for call in calls:
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            command_id = args.get("command")
            path = args.get("path")

            output = None
            async for event in _run_tool(command_id, path):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            commands_run.append(
                CommandRun(command=str(command_id), label=command_label(command_id), path=path, output=output)
            )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    yield _final_event(parse_disk_report(final_text), narration, commands_run)


async def _run_openai(api_key, model_id, message):
    async for event in _run_openai_compatible(
        "https://api.openai.com/v1/chat/completions", api_key, model_id, message
    ):
        yield event


async def _run_groq(api_key, model_id, message):
    async for event in _run_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions", api_key, model_id, message
    ):
        yield event


# ---- Gemini ----

def _gemini_tool_schema():
    return [{
        "functionDeclarations": [{
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "command": {
                        "type": "STRING",
                        "enum": list(DISK_COMMANDS.keys()),
                        "description": _command_enum_description(),
                    },
                    "path": {"type": "STRING", "description": PATH_DESCRIPTION},
                },
                "required": ["command"],
            },
        }],
    }]


async def _gemini_round(url, api_key, contents, tools, result):
    payload = {
        "system_instruction": {"parts": [{"text": DISK_AGENT_SYSTEM_PROMPT}]},
        "contents": contents,
    }
    if tools:
        payload["tools"] = tools

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        retry_after = None
        buffered = ""
        parts = []

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                async with client.stream(
                    "POST", url, params={"key": api_key, "alt": "sse"}, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")
                        if is_rate_limited(response.status_code) and attempt < MAX_RATE_LIMIT_RETRIES:
                            retry_after = retry_delay(response.headers, body, attempt)
                        else:
                            result["error"] = f"{response.status_code}: {body[:300]}"
                            result["rate_limited"] = is_rate_limited(response.status_code)
                            return
                    else:
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:"):].strip()
                            if not data:
                                continue

                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue

                            candidates = chunk.get("candidates") or []
                            if not candidates:
                                continue

                            for part in candidates[0].get("content", {}).get("parts", []) or []:
                                parts.append(part)
                                text = part.get("text")
                                if text:
                                    narration = _narration_delta(buffered, text)
                                    buffered += text
                                    if narration:
                                        yield {"type": "thinking_delta", "text": narration}
        except httpx.HTTPError as e:
            result["error"] = str(e)
            return

        if retry_after is not None:
            yield {"type": "rate_limited", "retry_in": retry_after, "attempt": attempt + 1}
            await wait_before_retry(retry_after, attempt)
            continue

        result["text"] = buffered
        result["parts"] = parts
        return


async def _run_gemini(api_key, model_id, message):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:streamGenerateContent"
    tools = _gemini_tool_schema()
    contents = [{"role": "user", "parts": [{"text": message}]}]
    commands_run = []
    narration = ""
    final_text = ""

    for round_index in range(MAX_TOOL_ROUNDS + 1):
        round_tools = tools if round_index < MAX_TOOL_ROUNDS else None

        result = {}
        async for event in _gemini_round(url, api_key, contents, round_tools, result):
            if event["type"] == "thinking_delta":
                narration += event["text"]
            yield event

        if "error" in result:
            yield {
                "type": "error",
                "detail": result["error"],
                "status": 429 if result.get("rate_limited") else 502,
            }
            return

        if (result.get("text") or "").strip():
            final_text = result["text"]

        parts = result.get("parts") or []
        function_calls = [part["functionCall"] for part in parts if "functionCall" in part]

        if not function_calls:
            if _has_report(result.get("text")) or round_index == MAX_TOOL_ROUNDS:
                final_text = result.get("text", "") or final_text
                break
            # Narrated but never called the tool or gave a report - nudge it and try again.
            contents.append({"role": "model", "parts": parts or [{"text": result.get("text", "")}]})
            contents.append({"role": "user", "parts": [{"text": NUDGE_MESSAGE}]})
            continue

        contents.append({"role": "model", "parts": parts})
        response_parts = []
        for call in function_calls:
            args = call.get("args") or {}
            command_id = args.get("command")
            path = args.get("path")

            output = None
            async for event in _run_tool(command_id, path):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            commands_run.append(
                CommandRun(command=str(command_id), label=command_label(command_id), path=path, output=output)
            )
            response_parts.append({
                "functionResponse": {"name": call.get("name", TOOL_NAME), "response": {"result": output}}
            })

        contents.append({"role": "user", "parts": response_parts})

    yield _final_event(parse_disk_report(final_text), narration, commands_run)


_AGENTS = {
    "anthropic": _run_anthropic,
    "openai": _run_openai,
    "gemini": _run_gemini,
    "groq": _run_groq,
}


async def run_disk_agent(provider, api_key, model_id, message):
    agent = _AGENTS.get(provider)
    if agent is None:
        yield {"type": "error", "detail": f"unknown provider: {provider}"}
        return
    async for event in agent(api_key, model_id, message):
        yield event
