"""Per-provider tool loops for the network agent.

Written against the process agent's `tool_clients.py`, which was itself written against the disk
agent's - the reference implementation for this pattern: four rounds of tool calls, a nudge for a
model that narrates without acting, a final round with the tools withheld to force the report out,
rate-limit and transient retries that never replay a round which already streamed, and exactly one
terminal event on every exit path.

The loops are deliberately not shared between the three agents. Four providers' streaming and
tool-calling formats differ enough that a single parameterised loop would be a worse abstraction than
three honest copies, and disk stays the stable reference the others are checked against. What is
shared lives in `agents/shared.py`, and needed no changes to admit a third agent: the
`request_command` schemas were already parameterised on the calling agent's own tool name.
"""
import asyncio
import json
import logging

import anthropic
import httpx

from routers.orchestrator.ratelimit import (
    MAX_RATE_LIMIT_RETRIES,
    MAX_TRANSIENT_RETRIES,
    is_rate_limited,
    is_transient_status,
    retry_delay,
    space_calls,
    transient_delay,
    wait_before_retry,
    wait_before_transient_retry,
)
from routers.orchestrator.agents import shared
from routers.orchestrator.agents.shared import COMMAND_TOOL_NAME
from routers.orchestrator.schemas import CommandRun
from routers.orchestrator.tools.network.tool import (
    NETWORK_COMMANDS,
    command_label,
    tool_schema_properties,
)

from .prompt import NETWORK_AGENT_SYSTEM_PROMPT
from .xml import parse_network_report

logger = logging.getLogger("orchestrator.network")

AGENT_NAME = "network"
REPORT_TAG = "network_report"
TOOL_NAME = "run_network_command"
TOOL_DESCRIPTION = (
    "Run one read-only diagnostic command about connectivity, interfaces, wireless, routing, DNS, "
    "sockets, ports or firewalls, and return its output. Some commands take an argument: an interface "
    "name, a hostname or IP address, or a port number. For 'is my internet working' or any fault "
    "report, use connectivity_check. For 'what is using my network', use app_connections."
)
ARG_DESCRIPTION = (
    "Optional argument for commands that take one. The command's own description says which kind it "
    "wants: an interface name such as wlan0, a hostname or IP address such as example.com or 1.1.1.1, "
    "or a port number such as 443. Omit it for commands that take no argument."
)
MAX_TOOL_ROUNDS = 4
# Nudges do not consume a tool round, so they need their own ceiling to bound the turn.
MAX_NUDGES = 2
MAX_TOOL_RETRIES = 2
MAX_TOKENS = 16000
_HTTP_TIMEOUT = 120.0

INTERNAL_API_BASE = shared.INTERNAL_API_BASE

FINAL_ROUND_MESSAGE = shared.final_round_message(REPORT_TAG)
NUDGE_MESSAGE = shared.nudge_message(TOOL_NAME, REPORT_TAG)

_narration_chunk = shared.narration_chunk


def _has_report(text):
    return shared.has_report(text, REPORT_TAG)


def _command_enum_description():
    """Only the first sentence of each command's description. The full text is useful reading in the
    source, but this string ships on every round of every request, so the extra detail is a real
    token cost against a provider's per-minute budget."""
    parts = []
    for cid, description in tool_schema_properties().items():
        parts.append(f"{cid}: {description.split('. ')[0].rstrip('.')}")
    return "; ".join(parts)


async def _call_network_tool(command_id, arg=None):
    """Calls the network tool over its real HTTP route (loopback) rather than the function directly.

    Retries transient failures, because the alternative is handing the model an error string it will
    reason about as though the machine had actually reported that - a dropped loopback connection
    must not become a finding about the user's network. Never raises: a failure that survives
    the retries becomes an error string, which is an honest answer the model can report."""
    params = {"arg": arg} if arg else None
    url = f"{INTERNAL_API_BASE}/linux/tools/network/{command_id}"

    for attempt in range(MAX_TOOL_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.get(url, params=params)

            # A 404 is the tool route telling us the command id is unknown. That is a settled
            # answer, not a transient fault, so it is returned rather than retried.
            if response.status_code == 404:
                return response.json().get("detail", f"Unknown command '{command_id}'")

            if is_transient_status(response.status_code) and attempt < MAX_TOOL_RETRIES:
                logger.warning(
                    f"network tool '{command_id}' returned {response.status_code}, retry {attempt + 1}"
                )
                await asyncio.sleep(transient_delay(attempt))
                continue

            response.raise_for_status()
            return response.json()["output"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            if attempt < MAX_TOOL_RETRIES:
                logger.warning(f"network tool '{command_id}' failed ({e}), retry {attempt + 1}")
                await asyncio.sleep(transient_delay(attempt))
                continue
            return f"Error calling network tool '{command_id}': {e}"

    return f"Error calling network tool '{command_id}': exhausted {MAX_TOOL_RETRIES} retries"


async def _run_tool(command_id, arg=None):
    label = command_label(command_id)
    # The trace panel keys rows on `path`, so the argument travels under that name regardless of
    # whether it is an interface, a host or a port.
    yield {"type": "tool_call", "agent": AGENT_NAME, "command": command_id, "label": label, "path": arg}
    output = await _call_network_tool(command_id, arg)
    yield {
        "type": "tool_result",
        "agent": AGENT_NAME,
        "command": command_id,
        "label": label,
        "path": arg,
        "output": output,
    }


async def _dispatch_tool(name, args):
    """Routes one tool call to its handler. Every path ends with a tool_result event carrying the
    output, so callers can collect it uniformly."""
    if name == COMMAND_TOOL_NAME:
        async for event in shared.run_command_request(
            AGENT_NAME, args.get("argv"), args.get("reason"), args.get("count_lines")
        ):
            yield event
        return

    async for event in _run_tool(args.get("command"), args.get("arg")):
        yield event


def _record_command(commands_run, name, args, output):
    """Adds one executed tool call to the trace record."""
    if name == COMMAND_TOOL_NAME:
        argv = [str(token) for token in (args.get("argv") or [])]
        label = " ".join(argv) or "(no command)"
        commands_run.append(
            CommandRun(command=label, label="Approved command", path=None, output=output)
        )
        return

    command_id = args.get("command")
    commands_run.append(
        CommandRun(
            command=str(command_id),
            label=command_label(command_id),
            path=args.get("arg"),
            output=output,
        )
    )


def _final_event(network_report, thinking, commands_run):
    return {
        "type": "final",
        "mode": AGENT_NAME,
        "thinking": thinking.strip() or None,
        "network_report": network_report.model_dump(),
        "commands_run": [cr.model_dump() for cr in commands_run],
    }


# ---- Anthropic ----

def _anthropic_tool_schema():
    return [
        {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": list(NETWORK_COMMANDS.keys()),
                        "description": _command_enum_description(),
                    },
                    "arg": {"type": "string", "description": ARG_DESCRIPTION},
                },
                "required": ["command"],
            },
        },
        shared.anthropic_command_tool(TOOL_NAME),
    ]


async def _anthropic_round(client, model_id, messages, tools, result):
    kwargs = {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "system": NETWORK_AGENT_SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    transient_attempts = 0

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        buffered = ""
        narrated = 0
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                        buffered += event.delta.text
                        narration, narrated = _narration_chunk(buffered, narrated)
                        if narration:
                            yield {"type": "thinking_delta", "text": narration}
                narration, narrated = _narration_chunk(buffered, narrated, complete=True)
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
        except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            # Retrying a round that already streamed narration would replay it on the client, so
            # only a round that produced nothing yet can be replayed.
            if narrated or transient_attempts >= MAX_TRANSIENT_RETRIES:
                result["error"] = str(e)
                return
            delay = transient_delay(transient_attempts)
            yield {"type": "retrying", "retry_in": delay, "attempt": transient_attempts + 1}
            await wait_before_transient_retry(delay, transient_attempts, str(e)[:120])
            transient_attempts += 1
        except anthropic.APIError as e:
            result["error"] = str(e)
            return

    result.setdefault("error", "provider retries exhausted without a response")


async def _run_anthropic(api_key, model_id, message):
    client = anthropic.AsyncAnthropic(api_key=api_key)
    tools = _anthropic_tool_schema()
    messages = [{"role": "user", "content": message}]
    commands_run = []
    narration = ""
    final_text = ""
    nudges = 0
    round_index = 0

    while round_index <= MAX_TOOL_ROUNDS:
        # The extra final round runs without tools and says so in the conversation, so the model
        # knows its budget is gone rather than silently losing the ability to act.
        final_round = round_index == MAX_TOOL_ROUNDS
        round_tools = None if final_round else tools
        if final_round:
            messages.append({"role": "user", "content": FINAL_ROUND_MESSAGE})

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
            if _has_report(text) or final_round:
                break
            if nudges >= MAX_NUDGES:
                # Out of nudges: go straight to the forced-answer round rather than giving up, so a
                # stalling model is still asked outright for the report.
                round_index = MAX_TOOL_ROUNDS
                continue
            # Narrated but never called the tool or gave a report - nudge without spending a tool
            # round, so a model that stalls early keeps its full investigation budget.
            nudges += 1
            if response.content:
                messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            continue

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            args = block.input or {}
            output = None
            async for event in _dispatch_tool(block.name, args):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            _record_command(commands_run, block.name, args, output)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": tool_results})
        round_index += 1

    yield _final_event(parse_network_report(final_text), narration, commands_run)


# ---- OpenAI / Groq (OpenAI-compatible) ----

def _openai_tool_schema():
    return [
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": list(NETWORK_COMMANDS.keys()),
                            "description": _command_enum_description(),
                        },
                        "arg": {"type": "string", "description": ARG_DESCRIPTION},
                    },
                    "required": ["command"],
                },
            },
        },
        shared.openai_command_tool(TOOL_NAME),
    ]


async def _openai_round(base_url, api_key, model_id, messages, tools, result):
    payload = {"model": model_id, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    transient_attempts = 0

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        retry_after = None
        transient_reason = None
        buffered = ""
        narrated = 0
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
                        elif (
                            is_transient_status(response.status_code)
                            and transient_attempts < MAX_TRANSIENT_RETRIES
                        ):
                            transient_reason = f"{response.status_code}: {body[:120]}"
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
                                buffered += text
                                narration, narrated = _narration_chunk(buffered, narrated)
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
            # Retrying a round that already streamed narration or collected tool-call fragments
            # would replay them on the client, so only an untouched round can be replayed.
            if narrated or tool_calls or transient_attempts >= MAX_TRANSIENT_RETRIES:
                result["error"] = str(e)
                return
            transient_reason = str(e)[:120]

        if retry_after is not None:
            yield {"type": "rate_limited", "retry_in": retry_after, "attempt": attempt + 1}
            await wait_before_retry(retry_after, attempt)
            continue

        if transient_reason is not None:
            delay = transient_delay(transient_attempts)
            yield {"type": "retrying", "retry_in": delay, "attempt": transient_attempts + 1}
            await wait_before_transient_retry(delay, transient_attempts, transient_reason)
            transient_attempts += 1
            continue

        narration, narrated = _narration_chunk(buffered, narrated, complete=True)
        if narration:
            yield {"type": "thinking_delta", "text": narration}

        result["text"] = buffered
        result["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return

    result.setdefault("error", "provider retries exhausted without a response")


async def _run_openai_compatible(base_url, api_key, model_id, message):
    tools = _openai_tool_schema()
    messages = [
        {"role": "system", "content": NETWORK_AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    commands_run = []
    narration = ""
    final_text = ""
    nudges = 0
    round_index = 0

    while round_index <= MAX_TOOL_ROUNDS:
        # The extra final round runs without tools and says so in the conversation, so the model
        # knows its budget is gone rather than silently losing the ability to act.
        final_round = round_index == MAX_TOOL_ROUNDS
        round_tools = None if final_round else tools
        if final_round:
            messages.append({"role": "user", "content": FINAL_ROUND_MESSAGE})

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
            if _has_report(result.get("text")) or final_round:
                final_text = result.get("text", "") or final_text
                break
            if nudges >= MAX_NUDGES:
                # Out of nudges: go straight to the forced-answer round rather than giving up, so a
                # stalling model is still asked outright for the report.
                round_index = MAX_TOOL_ROUNDS
                continue
            # Narrated but never called the tool or gave a report - nudge without spending a tool
            # round, so a model that stalls early keeps its full investigation budget. An assistant
            # message with neither content nor tool_calls is rejected by these APIs, so a round that
            # produced nothing at all is not echoed back.
            nudges += 1
            if (result.get("text") or "").strip():
                messages.append({"role": "assistant", "content": result["text"]})
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

            output = None
            async for event in _dispatch_tool(call["name"], args):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            _record_command(commands_run, call["name"], args, output)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

        round_index += 1

    yield _final_event(parse_network_report(final_text), narration, commands_run)


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
        "functionDeclarations": [
            {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "command": {
                            "type": "STRING",
                            "enum": list(NETWORK_COMMANDS.keys()),
                            "description": _command_enum_description(),
                        },
                        "arg": {"type": "STRING", "description": ARG_DESCRIPTION},
                    },
                    "required": ["command"],
                },
            },
            shared.gemini_command_tool(TOOL_NAME),
        ],
    }]


async def _gemini_round(url, api_key, contents, tools, result):
    payload = {
        "system_instruction": {"parts": [{"text": NETWORK_AGENT_SYSTEM_PROMPT}]},
        "contents": contents,
    }
    if tools:
        payload["tools"] = tools

    transient_attempts = 0

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        retry_after = None
        transient_reason = None
        buffered = ""
        narrated = 0
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
                        elif (
                            is_transient_status(response.status_code)
                            and transient_attempts < MAX_TRANSIENT_RETRIES
                        ):
                            transient_reason = f"{response.status_code}: {body[:120]}"
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
                                    buffered += text
                                    narration, narrated = _narration_chunk(buffered, narrated)
                                    if narration:
                                        yield {"type": "thinking_delta", "text": narration}
        except httpx.HTTPError as e:
            # Retrying a round that already streamed narration or collected parts would replay them
            # on the client, so only an untouched round can be replayed.
            if narrated or parts or transient_attempts >= MAX_TRANSIENT_RETRIES:
                result["error"] = str(e)
                return
            transient_reason = str(e)[:120]

        if retry_after is not None:
            yield {"type": "rate_limited", "retry_in": retry_after, "attempt": attempt + 1}
            await wait_before_retry(retry_after, attempt)
            continue

        if transient_reason is not None:
            delay = transient_delay(transient_attempts)
            yield {"type": "retrying", "retry_in": delay, "attempt": transient_attempts + 1}
            await wait_before_transient_retry(delay, transient_attempts, transient_reason)
            transient_attempts += 1
            continue

        narration, narrated = _narration_chunk(buffered, narrated, complete=True)
        if narration:
            yield {"type": "thinking_delta", "text": narration}

        result["text"] = buffered
        result["parts"] = parts
        return

    result.setdefault("error", "provider retries exhausted without a response")


async def _run_gemini(api_key, model_id, message):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:streamGenerateContent"
    tools = _gemini_tool_schema()
    contents = [{"role": "user", "parts": [{"text": message}]}]
    commands_run = []
    narration = ""
    final_text = ""
    nudges = 0
    round_index = 0

    while round_index <= MAX_TOOL_ROUNDS:
        # The extra final round runs without tools and says so in the conversation, so the model
        # knows its budget is gone rather than silently losing the ability to act.
        final_round = round_index == MAX_TOOL_ROUNDS
        round_tools = None if final_round else tools
        if final_round:
            contents.append({"role": "user", "parts": [{"text": FINAL_ROUND_MESSAGE}]})

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
            if _has_report(result.get("text")) or final_round:
                final_text = result.get("text", "") or final_text
                break
            if nudges >= MAX_NUDGES:
                # Out of nudges: go straight to the forced-answer round rather than giving up, so a
                # stalling model is still asked outright for the report.
                round_index = MAX_TOOL_ROUNDS
                continue
            # Narrated but never called the tool or gave a report - nudge without spending a tool
            # round, so a model that stalls early keeps its full investigation budget. A model turn
            # with no parts at all is rejected, so an empty round is not echoed back.
            nudges += 1
            if parts:
                contents.append({"role": "model", "parts": parts})
            contents.append({"role": "user", "parts": [{"text": NUDGE_MESSAGE}]})
            continue

        contents.append({"role": "model", "parts": parts})
        response_parts = []
        for call in function_calls:
            args = call.get("args") or {}
            name = call.get("name", TOOL_NAME)

            output = None
            async for event in _dispatch_tool(name, args):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            _record_command(commands_run, name, args, output)
            response_parts.append({
                "functionResponse": {"name": name, "response": {"result": output}}
            })

        contents.append({"role": "user", "parts": response_parts})
        round_index += 1

    yield _final_event(parse_network_report(final_text), narration, commands_run)


_AGENTS = {
    "anthropic": _run_anthropic,
    "openai": _run_openai,
    "gemini": _run_gemini,
    "groq": _run_groq,
}


async def run_network_agent(provider, api_key, model_id, message):
    """Streams the agent's events, guaranteeing the stream ends with exactly one terminal event.

    The client collapses its trace panel when the turn ends, so a run that stops without a "final"
    or "error" leaves the user staring at a finished-looking panel and no answer. Every exit path
    therefore produces one."""
    agent = _AGENTS.get(provider)
    if agent is None:
        yield {"type": "error", "status": 400, "detail": f"unknown provider: {provider}"}
        return

    saw_terminal = False
    try:
        async for event in agent(api_key, model_id, message):
            if event["type"] in ("final", "error"):
                saw_terminal = True
            yield event
    except Exception as e:
        logger.exception("network agent failed")
        if not saw_terminal:
            yield {"type": "error", "status": 502, "detail": f"network agent failed: {e}"}
        return

    if not saw_terminal:
        logger.error("network agent finished without a terminal event")
        yield {"type": "error", "status": 502, "detail": "network agent produced no result"}
