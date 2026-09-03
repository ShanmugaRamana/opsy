import json
import logging
import os

import anthropic
import httpx

from routers.orchestrator.schemas import CommandRun
from routers.tools.disk.tool import DISK_COMMANDS, command_label, tool_schema_properties

from .prompt import DISK_AGENT_SYSTEM_PROMPT
from .xml import parse_disk_report

logger = logging.getLogger("orchestrator.disk")

TOOL_NAME = "run_disk_command"
TOOL_DESCRIPTION = "Run one read-only diagnostic command about disk/storage usage and return its output."
_HTTP_TIMEOUT = 60.0

INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")


def _tool_description_text():
    return "; ".join(f"{cid}: {desc}" for cid, desc in tool_schema_properties().items())


async def _call_disk_tool(command_id):
    """Calls the disk tool over its real HTTP route (loopback) rather than the function directly.
    Never raises - any failure (network, 404, unexpected shape) becomes an error string, same
    contract the in-process version had."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"{INTERNAL_API_BASE}/linux/tools/disk/{command_id}")
        if response.status_code == 404:
            return response.json().get("detail", f"Unknown command '{command_id}'")
        response.raise_for_status()
        return response.json()["output"]
    except (httpx.HTTPError, KeyError) as e:
        return f"Error calling disk tool '{command_id}': {e}"


async def _run_tool(command_id):
    label = command_label(command_id)
    yield {"type": "tool_call", "agent": "disk", "command": command_id, "label": label}
    output = await _call_disk_tool(command_id)
    yield {"type": "tool_result", "agent": "disk", "command": command_id, "label": label, "output": output}


def _final_event(disk_report, thinking, commands_run):
    return {
        "type": "final",
        "mode": "disk",
        "thinking": thinking,
        "disk_report": disk_report.model_dump(),
        "commands_run": [cr.model_dump() for cr in commands_run],
    }


# ---- Anthropic: native tool_use / tool_result blocks ----

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
                    "description": _tool_description_text(),
                }
            },
            "required": ["command"],
        },
    }


async def _run_anthropic(api_key, model_id, message):
    client = anthropic.AsyncAnthropic(api_key=api_key)
    tools = [_anthropic_tool_schema()]
    messages = [{"role": "user", "content": message}]

    try:
        response = await client.messages.create(
            model=model_id, max_tokens=16000, system=DISK_AGENT_SYSTEM_PROMPT, tools=tools, messages=messages
        )
    except anthropic.APIError as e:
        yield {"type": "error", "detail": str(e)}
        return

    tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
    thinking_text = None
    commands_run = []

    if tool_use_blocks:
        # only meaningful when the model also explained itself before calling a tool - if there's
        # no tool call, this same text is the final answer (captured as final_text below instead),
        # not "thinking"
        thinking_text = next((b.text for b in response.content if b.type == "text"), None)
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            command_id = block.input.get("command")
            output = None
            async for event in _run_tool(command_id):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            commands_run.append(CommandRun(command=command_id, label=command_label(command_id), output=output))
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": tool_results})

        try:
            response = await client.messages.create(
                model=model_id, max_tokens=16000, system=DISK_AGENT_SYSTEM_PROMPT, messages=messages
            )
        except anthropic.APIError as e:
            yield {"type": "error", "detail": str(e)}
            return

    final_text = next((b.text for b in response.content if b.type == "text"), "")
    yield _final_event(parse_disk_report(final_text), thinking_text, commands_run)


# ---- OpenAI / Groq: OpenAI-compatible function calling ----

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
                        "description": _tool_description_text(),
                    }
                },
                "required": ["command"],
            },
        },
    }]


async def _run_openai_compatible(base_url, api_key, model_id, message):
    tools = _openai_tool_schema()
    messages = [
        {"role": "system", "content": DISK_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model_id, "messages": messages, "tools": tools, "tool_choice": "auto"},
            )
        response.raise_for_status()
        message_obj = response.json()["choices"][0]["message"]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        yield {"type": "error", "detail": str(e)}
        return

    tool_calls = message_obj.get("tool_calls") or []
    thinking_text = None
    commands_run = []

    if tool_calls:
        thinking_text = message_obj.get("content")
        messages.append(message_obj)
        for call in tool_calls:
            try:
                args = json.loads(call["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            command_id = args.get("command")

            output = None
            async for event in _run_tool(command_id):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            commands_run.append(CommandRun(command=command_id, label=command_label(command_id), output=output))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    base_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model_id, "messages": messages},
                )
            response.raise_for_status()
            message_obj = response.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            yield {"type": "error", "detail": str(e)}
            return

    final_text = message_obj.get("content") or ""
    yield _final_event(parse_disk_report(final_text), thinking_text, commands_run)


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


# ---- Gemini: functionCall / functionResponse ----

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
                        "description": _tool_description_text(),
                    }
                },
                "required": ["command"],
            },
        }],
    }]


async def _run_gemini(api_key, model_id, message):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    contents = [{"role": "user", "parts": [{"text": message}]}]

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                params={"key": api_key},
                json={
                    "system_instruction": {"parts": [{"text": DISK_AGENT_SYSTEM_PROMPT}]},
                    "contents": contents,
                    "tools": _gemini_tool_schema(),
                },
            )
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
    except (httpx.HTTPError, KeyError, IndexError) as e:
        yield {"type": "error", "detail": str(e)}
        return

    function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
    thinking_text = None
    commands_run = []

    if function_calls:
        thinking_text = next((p["text"] for p in parts if "text" in p), None)
        contents.append({"role": "model", "parts": parts})
        response_parts = []
        for call in function_calls:
            command_id = call.get("args", {}).get("command")

            output = None
            async for event in _run_tool(command_id):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            commands_run.append(CommandRun(command=command_id, label=command_label(command_id), output=output))
            response_parts.append({
                "functionResponse": {"name": call.get("name", TOOL_NAME), "response": {"result": output}}
            })

        contents.append({"role": "user", "parts": response_parts})

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    url,
                    params={"key": api_key},
                    json={
                        "system_instruction": {"parts": [{"text": DISK_AGENT_SYSTEM_PROMPT}]},
                        "contents": contents,
                    },
                )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            yield {"type": "error", "detail": str(e)}
            return

    final_text = "".join(p.get("text", "") for p in parts)
    yield _final_event(parse_disk_report(final_text), thinking_text, commands_run)


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
