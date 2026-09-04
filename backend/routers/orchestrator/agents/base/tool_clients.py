"""The base agent's per-provider tool loops.

Structurally this is the disk agent's tool_clients.py with a different tool set and a different
answer shape, and that duplication is deliberate - the same reason it is deliberate there. Four
providers' streaming formats differ in every direction that matters, and a shared abstraction over
them costs more than it saves.

Two things are genuinely different here, and both are about where the reasoning lives. The report
agents write prose before their XML, so they stream everything up to the first tag. The base agent
writes its reasoning inside <thinking>, in the same block as the answer, so it streams through
xml_common.ThinkingStream instead: it emits <thinking>, and withholds <content>, which the user
receives once as the answer rather than twice.
"""
import asyncio
import json
import logging

import anthropic
import httpx

from routers.orchestrator import xml_common
from routers.orchestrator.agents import shared
from routers.orchestrator.agents.shared import COMMAND_TOOL_NAME
from routers.orchestrator.memory.short_term.render import as_anthropic, as_gemini, as_openai
from routers.orchestrator.ratelimit import (
    MAX_RATE_LIMIT_RETRIES,
    MAX_TRANSIENT_RETRIES,
    can_retry_rate_limit,
    is_rate_limited,
    is_transient_status,
    mark_call_end,
    retry_delay,
    space_calls,
    transient_delay,
    wait_before_retry,
    wait_before_transient_retry,
)
from routers.orchestrator.schemas import CommandRun
from routers.orchestrator.tools.system.tool import SYSTEM_COMMANDS, command_label, tool_schema_properties

from .prompt import BASE_AGENT_SYSTEM_PROMPT
from .xml import parse_base_answer

logger = logging.getLogger("orchestrator.base")

AGENT_NAME = "base"
# The mode the orchestrator classified the turn as, and the key this agent is registered under.
AGENT_MODE = "general"
REPORT_TAG = "response"

# The allow-list group, this agent's primary tool - the same relationship run_disk_command has to the
# disk agent.
TOOL_NAME = "run_system_command"
TOOL_DESCRIPTION = (
    "Run one read-only command about what this machine is - its OS, kernel, uptime, time and locale, "
    "who is using it, and which programs and packages are installed - and return its output. Some "
    "commands need a name (a program or package)."
)
NAME_DESCRIPTION = (
    "The program or package to look up, for the commands that take one (which_binary, package_info). "
    "A plain name such as \"docker\" or \"python3\", never an option or a path."
)

# The hardware profile, which is a route rather than a command: it is served by the same collector
# the setup page uses, so the agent reads the machine's specs without spawning anything.
PROFILE_TOOL_NAME = "get_system_info"
PROFILE_TOOL_LABEL = "System information"
PROFILE_TOOL_DESCRIPTION = (
    "Return this machine's hardware profile: operating system, CPU model and cores, total and used "
    "RAM, GPU, and total and free storage. Takes no arguments. Call it whenever the answer depends "
    "on the hardware - how much memory or storage there is, or whether the machine is capable of "
    "something."
)

# The same budget the report agents get. A question that reached the base agent is one no specialist
# claimed, which makes it the agent most likely to need room to look around, not the least.
MAX_TOOL_ROUNDS = 4
# Nudges do not consume a tool round, so they need their own ceiling to bound the turn.
MAX_NUDGES = 2
# Ollama-only: how many times a round where every tool call used an invalid command id gets
# corrected for free (no round spent) before it starts costing a real tool round. See _run_ollama.
MAX_INVALID_TOOL_RETRIES = 2
MAX_TOOL_RETRIES = 2
MAX_TOKENS = 16000
_HTTP_TIMEOUT = 120.0

INTERNAL_API_BASE = shared.INTERNAL_API_BASE

FINAL_ROUND_MESSAGE = (
    "You have used all of your tool rounds and cannot run anything else. Answer now, from what you "
    f"already know and have observed, with ONLY the <{REPORT_TAG}> XML and nothing else. If "
    "something could not be determined, say so inside your answer rather than asking to check "
    "further."
)
NUDGE_MESSAGE = (
    f"You did not call a tool or give your final answer. Either call {TOOL_NAME}, "
    f"{PROFILE_TOOL_NAME} or {COMMAND_TOOL_NAME} now for whatever you still need to check, or, if "
    f"you can already answer, respond with ONLY the <{REPORT_TAG}> XML and nothing else. Do not tell "
    "the user to check something themselves."
)


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


# ---- Tools ----

def _format_profile(profile):
    """The hardware profile as plain lines rather than raw JSON.

    Every field is optional and any of them can come back null on a machine where the collector could
    not read it. Absent values are left out entirely instead of being reported as "None", because a
    model reading "RAM: None" will write it into an answer as though it were a finding."""
    cpu = profile.get("cpu") or {}
    ram = profile.get("ram") or {}
    gpu = profile.get("gpu") or {}
    storage = profile.get("storage") or {}

    lines = []
    if profile.get("os"):
        lines.append(f"OS: {profile['os']}")
    if cpu.get("model") or cpu.get("cores"):
        detail = ", ".join(
            part for part in (cpu.get("model"), f"{cpu['cores']} cores" if cpu.get("cores") else None)
            if part
        )
        lines.append(f"CPU: {detail}")
    if cpu.get("usage_percent") is not None:
        lines.append(f"CPU usage right now: {cpu['usage_percent']:g}%")
    if ram.get("total_gb") is not None:
        used = f", {ram['used_gb']:g} GB in use" if ram.get("used_gb") is not None else ""
        lines.append(f"RAM: {ram['total_gb']:g} GB total{used}")
    if gpu.get("model"):
        detail = [gpu["model"]]
        if gpu.get("vram_gb") is not None:
            detail.append(f"{gpu['vram_gb']:g} GB VRAM")
        if gpu.get("dedicated") is not None:
            detail.append("dedicated" if gpu["dedicated"] else "integrated")
        lines.append(f"GPU: {', '.join(detail)}")
    if storage.get("total_gb") is not None:
        free = f", {storage['free_gb']:g} GB free" if storage.get("free_gb") is not None else ""
        lines.append(f"Storage: {storage['total_gb']:g} GB total{free}")

    if not lines:
        return "The hardware profile came back empty - none of these details could be read on this machine."

    # Named for what it is, so the model does not mistake a whole-machine total for a per-filesystem
    # figure the disk agent would have measured.
    return "Machine profile:\n" + "\n".join(lines)


async def _call_system_info():
    """Calls the hardware profile over its real HTTP route (loopback) rather than the collector
    directly, the same way every agent reaches every tool here.

    Never raises: a failure that survives the retries becomes an error string, which is an honest
    answer the model can report rather than a turn that dies."""
    url = f"{INTERNAL_API_BASE}/linux/hardware/profile"

    for attempt in range(MAX_TOOL_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)

            if is_transient_status(response.status_code) and attempt < MAX_TOOL_RETRIES:
                logger.warning(f"hardware profile returned {response.status_code}, retry {attempt + 1}")
                await asyncio.sleep(transient_delay(attempt))
                continue

            response.raise_for_status()
            return _format_profile(response.json())
        except (httpx.HTTPError, KeyError, ValueError) as e:
            if attempt < MAX_TOOL_RETRIES:
                logger.warning(f"hardware profile failed ({e}), retry {attempt + 1}")
                await asyncio.sleep(transient_delay(attempt))
                continue
            return f"Error reading this machine's hardware profile: {e}"

    return f"Error reading this machine's hardware profile: exhausted {MAX_TOOL_RETRIES} retries"


async def _call_system_tool(command_id, name=None):
    """Calls the system tool group over its real HTTP route (loopback) rather than the function
    directly, exactly as the disk agent calls its own group.

    Retries transient failures, because the alternative is handing the model an error string it will
    reason about as though the machine had actually reported that. Never raises: a failure that
    survives the retries becomes an error string, which is an honest answer the model can report."""
    params = {"name": name} if name else None
    url = f"{INTERNAL_API_BASE}/linux/tools/system/{command_id}"

    for attempt in range(MAX_TOOL_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, params=params)

            # A 404 is the tool route telling us the command id is unknown. That is a settled answer,
            # not a transient fault, so it is returned rather than retried.
            if response.status_code == 404:
                return response.json().get("detail", f"Unknown command '{command_id}'")

            if is_transient_status(response.status_code) and attempt < MAX_TOOL_RETRIES:
                logger.warning(f"system tool '{command_id}' returned {response.status_code}, retry {attempt + 1}")
                await asyncio.sleep(transient_delay(attempt))
                continue

            response.raise_for_status()
            return response.json()["output"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            if attempt < MAX_TOOL_RETRIES:
                logger.warning(f"system tool '{command_id}' failed ({e}), retry {attempt + 1}")
                await asyncio.sleep(transient_delay(attempt))
                continue
            return f"Error calling system tool '{command_id}': {e}"

    return f"Error calling system tool '{command_id}': exhausted {MAX_TOOL_RETRIES} retries"


async def _run_system_tool(command_id, name=None):
    label = command_label(command_id)
    yield {"type": "tool_call", "agent": AGENT_NAME, "command": command_id, "label": label, "path": name}
    output = await _call_system_tool(command_id, name)
    yield {
        "type": "tool_result",
        "agent": AGENT_NAME,
        "command": command_id,
        "label": label,
        "path": name,
        "output": output,
    }


async def _run_profile_tool():
    yield {
        "type": "tool_call", "agent": AGENT_NAME, "command": PROFILE_TOOL_NAME,
        "label": PROFILE_TOOL_LABEL, "path": None,
    }
    output = await _call_system_info()
    yield {
        "type": "tool_result",
        "agent": AGENT_NAME,
        "command": PROFILE_TOOL_NAME,
        "label": PROFILE_TOOL_LABEL,
        "path": None,
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

    if name == PROFILE_TOOL_NAME:
        async for event in _run_profile_tool():
            yield event
        return

    if name != TOOL_NAME:
        # A hallucinated tool name would otherwise be answered by one of the real tools, which the
        # model would then reason about as though it were what it asked for.
        yield {
            "type": "tool_result",
            "agent": AGENT_NAME,
            "command": name or "(unnamed)",
            "label": str(name or "unknown tool"),
            "path": None,
            "output": (
                f"There is no tool called '{name}'. This agent has {TOOL_NAME}, "
                f"{PROFILE_TOOL_NAME} and {COMMAND_TOOL_NAME}."
            ),
        }
        return

    async for event in _run_system_tool(args.get("command"), args.get("name")):
        yield event


def _record_command(commands_run, name, args, output):
    """Adds one executed tool call to the trace record."""
    if name == COMMAND_TOOL_NAME:
        argv = [str(token) for token in (args.get("argv") or [])]
        label = " ".join(argv) or "(no command)"
        commands_run.append(
            CommandRun(command=label, label="Approved command", path=None, output=output or "")
        )
        return

    if name == PROFILE_TOOL_NAME:
        commands_run.append(
            CommandRun(command=PROFILE_TOOL_NAME, label=PROFILE_TOOL_LABEL, path=None, output=output or "")
        )
        return

    command_id = args.get("command")
    if command_id is None:
        # Either a hallucinated tool name, or this agent's own tool called without a command id.
        # Recording what was actually asked for keeps the trace honest; the alternative reads as a
        # command literally called "None".
        commands_run.append(
            CommandRun(command=str(name), label=str(name), path=None, output=output or "")
        )
        return

    commands_run.append(
        CommandRun(
            command=str(command_id),
            label=command_label(command_id),
            path=args.get("name"),
            output=output or "",
        )
    )


def _final_event(final_text, narration, commands_run):
    """The turn's terminal event, in the shape the orchestrator stores and the client already
    renders: `content` is the answer bubble, `thinking` fills the trace panel on a replay, and
    `raw_xml` is the model's own reply, kept so a stored turn is the model's words rather than a
    round trip through this process."""
    thinking, content = parse_base_answer(final_text, narration)
    return {
        "type": "final",
        "mode": AGENT_MODE,
        "thinking": thinking,
        "content": content,
        "raw_xml": final_text or "",
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
                        "enum": list(SYSTEM_COMMANDS.keys()),
                        "description": _command_enum_description(),
                    },
                    "name": {"type": "string", "description": NAME_DESCRIPTION},
                },
                "required": ["command"],
            },
        },
        {
            "name": PROFILE_TOOL_NAME,
            "description": PROFILE_TOOL_DESCRIPTION,
            "input_schema": {"type": "object", "properties": {}},
        },
        shared.anthropic_command_tool(TOOL_NAME),
    ]


async def _anthropic_round(client, model_id, messages, tools, result):
    kwargs = {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "system": BASE_AGENT_SYSTEM_PROMPT,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools

    transient_attempts = 0

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        await space_calls()
        streamer = xml_common.ThinkingStream()
        streamed = 0
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                        thinking = streamer.feed(event.delta.text)
                        if thinking:
                            streamed += len(thinking)
                            yield {"type": "thinking_delta", "text": thinking}
                thinking = streamer.finish()
                if thinking:
                    yield {"type": "thinking_delta", "text": thinking}
                result["message"] = await stream.get_final_message()
            mark_call_end()
            return
        except anthropic.RateLimitError as e:
            headers = getattr(getattr(e, "response", None), "headers", None)
            if not can_retry_rate_limit(attempt, headers, str(e)):
                result["error"] = str(e)
                result["rate_limited"] = True
                return
            delay = retry_delay(headers, str(e), attempt)
            yield {"type": "rate_limited", "retry_in": delay, "attempt": attempt + 1}
            await wait_before_retry(delay, attempt)
        except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            # Retrying a round that already streamed thinking would replay it on the client, so only
            # a round that produced nothing yet can be replayed.
            if streamed or transient_attempts >= MAX_TRANSIENT_RETRIES:
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


async def _run_anthropic(api_key, model_id, message, base_url=None, history=None):
    client = anthropic.AsyncAnthropic(api_key=api_key)
    tools = _anthropic_tool_schema()
    messages = as_anthropic(history) + [{"role": "user", "content": message}]
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
                # stalling model is still asked outright for its answer.
                round_index = MAX_TOOL_ROUNDS
                continue
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

    yield _final_event(final_text, narration, commands_run)


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
                            "enum": list(SYSTEM_COMMANDS.keys()),
                            "description": _command_enum_description(),
                        },
                        "name": {"type": "string", "description": NAME_DESCRIPTION},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": PROFILE_TOOL_NAME,
                "description": PROFILE_TOOL_DESCRIPTION,
                "parameters": {"type": "object", "properties": {}},
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
        streamer = xml_common.ThinkingStream()
        streamed = 0
        tool_calls = {}

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                async with client.stream(
                    "POST", base_url, headers={"Authorization": f"Bearer {api_key}"}, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")
                        if is_rate_limited(response.status_code) and can_retry_rate_limit(
                            attempt, response.headers, body
                        ):
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
                                thinking = streamer.feed(text)
                                if thinking:
                                    streamed += len(thinking)
                                    yield {"type": "thinking_delta", "text": thinking}

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
            # Retrying a round that already streamed thinking or collected tool-call fragments would
            # replay them on the client, so only an untouched round can be replayed.
            if streamed or tool_calls or transient_attempts >= MAX_TRANSIENT_RETRIES:
                result["error"] = str(e)
                return
            transient_reason = str(e)[:120]

        mark_call_end()

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

        thinking = streamer.finish()
        if thinking:
            yield {"type": "thinking_delta", "text": thinking}

        result["text"] = buffered
        result["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return

    result.setdefault("error", "provider retries exhausted without a response")


async def _run_openai_compatible(base_url, api_key, model_id, message, history=None):
    tools = _openai_tool_schema()
    messages = [
        {"role": "system", "content": BASE_AGENT_SYSTEM_PROMPT},
        *as_openai(history),
        {"role": "user", "content": message},
    ]
    commands_run = []
    narration = ""
    final_text = ""
    nudges = 0
    round_index = 0

    while round_index <= MAX_TOOL_ROUNDS:
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
                break
            if nudges >= MAX_NUDGES:
                round_index = MAX_TOOL_ROUNDS
                continue
            # An assistant message with neither content nor tool_calls is rejected by these APIs, so
            # a round that produced nothing at all is not echoed back.
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

    yield _final_event(final_text, narration, commands_run)


async def _run_openai(api_key, model_id, message, base_url=None, history=None):
    async for event in _run_openai_compatible(
        "https://api.openai.com/v1/chat/completions", api_key, model_id, message, history=history,
    ):
        yield event


async def _run_groq(api_key, model_id, message, base_url=None, history=None):
    async for event in _run_openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions", api_key, model_id, message, history=history,
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
                            "enum": list(SYSTEM_COMMANDS.keys()),
                            "description": _command_enum_description(),
                        },
                        "name": {"type": "STRING", "description": NAME_DESCRIPTION},
                    },
                    "required": ["command"],
                },
            },
            # `parameters` is omitted rather than sent as an empty object: this tool takes no
            # arguments, and Gemini rejects a declaration whose parameter schema has no properties.
            {"name": PROFILE_TOOL_NAME, "description": PROFILE_TOOL_DESCRIPTION},
            shared.gemini_command_tool(TOOL_NAME),
        ],
    }]


async def _gemini_round(url, api_key, contents, tools, result):
    payload = {
        "system_instruction": {"parts": [{"text": BASE_AGENT_SYSTEM_PROMPT}]},
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
        streamer = xml_common.ThinkingStream()
        streamed = 0
        parts = []

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                async with client.stream(
                    "POST", url, params={"key": api_key, "alt": "sse"}, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(errors="replace")
                        if is_rate_limited(response.status_code) and can_retry_rate_limit(
                            attempt, response.headers, body
                        ):
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
                                    thinking = streamer.feed(text)
                                    if thinking:
                                        streamed += len(thinking)
                                        yield {"type": "thinking_delta", "text": thinking}
        except httpx.HTTPError as e:
            # Retrying a round that already streamed thinking or collected parts would replay them on
            # the client, so only an untouched round can be replayed.
            if streamed or parts or transient_attempts >= MAX_TRANSIENT_RETRIES:
                result["error"] = str(e)
                return
            transient_reason = str(e)[:120]

        mark_call_end()

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

        thinking = streamer.finish()
        if thinking:
            yield {"type": "thinking_delta", "text": thinking}

        result["text"] = buffered
        result["parts"] = parts
        return

    result.setdefault("error", "provider retries exhausted without a response")


async def _run_gemini(api_key, model_id, message, base_url=None, history=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:streamGenerateContent"
    tools = _gemini_tool_schema()
    contents = as_gemini(history) + [{"role": "user", "parts": [{"text": message}]}]
    commands_run = []
    narration = ""
    final_text = ""
    nudges = 0
    round_index = 0

    while round_index <= MAX_TOOL_ROUNDS:
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
                break
            if nudges >= MAX_NUDGES:
                round_index = MAX_TOOL_ROUNDS
                continue
            # A model turn with no parts at all is rejected, so an empty round is not echoed back.
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
            response_parts.append({"functionResponse": {"name": name, "response": {"result": output}}})

        contents.append({"role": "user", "parts": response_parts})
        round_index += 1

    yield _final_event(final_text, narration, commands_run)


# ---- Ollama ----
#
# The full tool set and the full round loop, same as every cloud provider - the standing rule is that
# a local provider drives the identical flow, never a trimmed one. Only the wire format differs, and
# that difference lives in shared.ollama_round, which is handed this agent's ThinkingStream so a local
# model's reasoning streams from inside <thinking> exactly like a cloud model's does.

def _ollama_tool_schema():
    # Same JSON shape the OpenAI-compatible schema uses - Ollama's /api/chat accepts the same
    # function-tool request format. Only response parsing differs (see shared.ollama_round).
    return _openai_tool_schema()


async def _run_ollama(api_key, model_id, message, base_url=None, history=None):
    tools = _ollama_tool_schema()
    messages = [
        {"role": "system", "content": BASE_AGENT_SYSTEM_PROMPT},
        *as_openai(history),
        {"role": "user", "content": message},
    ]
    commands_run = []
    narration = ""
    final_text = ""
    nudges = 0
    invalid_retries = 0
    round_index = 0

    while round_index <= MAX_TOOL_ROUNDS:
        final_round = round_index == MAX_TOOL_ROUNDS
        round_tools = None if final_round else tools
        if final_round:
            messages.append({"role": "user", "content": FINAL_ROUND_MESSAGE})

        result = {}
        async for event in shared.ollama_round(
            base_url, model_id, messages, round_tools, result,
            streamer_factory=xml_common.ThinkingStream,
        ):
            if event["type"] == "thinking_delta":
                narration += event["text"]
            yield event

        if "error" in result:
            yield {"type": "error", "detail": result["error"], "status": 502}
            return

        if (result.get("text") or "").strip():
            final_text = result["text"]

        calls = result.get("tool_calls") or []
        if not calls:
            if _has_report(result.get("text")) or final_round:
                break
            if nudges >= MAX_NUDGES:
                round_index = MAX_TOOL_ROUNDS
                continue
            nudges += 1
            if (result.get("text") or "").strip():
                messages.append({"role": "assistant", "content": result["text"]})
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            continue

        # Ollama's tool_calls carry arguments as a JSON object, not a string fragment, and pair a
        # tool result to its call by name rather than by an id (it doesn't emit one) - both are real
        # differences from the OpenAI dialect, not just cosmetic ones.
        parsed_calls = []
        for call in calls:
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            parsed_calls.append((call, args))

        # Ollama does not grammar-constrain tool arguments the way a schema-enforced API would, so a
        # weaker model can send a `command` that was never in the enum - typically a raw shell string
        # like "uname -a" instead of "kernel". Dispatching that always fails, so when EVERY call in
        # the round is unresolvable it is corrected here without spending a tool round (the same
        # no-cost-retry idea the nudge above uses), capped so a model that never recovers still
        # reaches the final forced round on schedule instead of looping forever on empty rounds.
        invalid_calls = [
            (call, args) for call, args in parsed_calls
            if call["name"] == TOOL_NAME and args.get("command") not in SYSTEM_COMMANDS
        ]

        if (
            invalid_calls
            and len(invalid_calls) == len(parsed_calls)
            and not final_round
            and invalid_retries < MAX_INVALID_TOOL_RETRIES
        ):
            invalid_retries += 1
            messages.append({
                "role": "assistant",
                "content": result.get("text") or "",
                "tool_calls": [
                    {"function": {"name": call["name"], "arguments": args}} for call, args in parsed_calls
                ],
            })
            for call, args in parsed_calls:
                bad = args.get("command")
                correction = (
                    f"'{bad}' is not a valid command id - there is no shell here, so a raw command "
                    f"like 'uname -a' cannot be passed directly. Pick exactly one id from this list: "
                    f"{', '.join(SYSTEM_COMMANDS)}. If none of them answer the question, call "
                    f"{COMMAND_TOOL_NAME} instead, with the command as an argv list."
                )
                messages.append({"role": "tool", "content": correction, "name": call["name"]})
            continue

        messages.append({
            "role": "assistant",
            "content": result.get("text") or "",
            "tool_calls": [
                {"function": {"name": call["name"], "arguments": args}} for call, args in parsed_calls
            ],
        })

        for call, args in parsed_calls:
            output = None
            async for event in _dispatch_tool(call["name"], args):
                if event["type"] == "tool_result":
                    output = event["output"]
                yield event
            _record_command(commands_run, call["name"], args, output)
            messages.append({"role": "tool", "content": output, "name": call["name"]})

        round_index += 1

    yield _final_event(final_text, narration, commands_run)


_AGENTS = {
    "anthropic": _run_anthropic,
    "openai": _run_openai,
    "gemini": _run_gemini,
    "groq": _run_groq,
    "ollama": _run_ollama,
}


async def run_base_agent(provider, api_key, model_id, message, base_url=None, history=None):
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
        async for event in agent(api_key, model_id, message, base_url=base_url, history=history):
            if event["type"] in ("final", "error"):
                saw_terminal = True
            yield event
    except Exception as e:
        logger.exception("base agent failed")
        if not saw_terminal:
            yield {"type": "error", "status": 502, "detail": f"base agent failed: {e}"}
        return

    if not saw_terminal:
        logger.error("base agent finished without a terminal event")
        yield {"type": "error", "status": 502, "detail": "base agent produced no result"}
