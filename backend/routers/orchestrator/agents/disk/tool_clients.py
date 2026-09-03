import asyncio
import json
import logging
import os
import re

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
from routers.orchestrator import permissions
from routers.orchestrator.schemas import CommandRun
from routers.orchestrator.tools.command.tool import validate_argv
from routers.orchestrator.tools.disk.tool import DISK_COMMANDS, command_label, tool_schema_properties

from .prompt import DISK_AGENT_SYSTEM_PROMPT
from .xml import parse_disk_report

logger = logging.getLogger("orchestrator.disk")

TOOL_NAME = "run_disk_command"
TOOL_DESCRIPTION = (
    "Run one read-only diagnostic command about disk or storage and return its output. "
    "Some commands accept a path (a directory, or a device such as /dev/sda)."
)
COMMAND_TOOL_NAME = "request_command"
COMMAND_TOOL_DESCRIPTION = (
    "Ask the user's permission to run one read-only command that run_disk_command does not cover, "
    "then run it if they approve. Use this only for a genuine gap - prefer run_disk_command whenever "
    "one of its commands fits. There is no shell: give the command as an argv list. A pipe, redirect "
    "or command-substitution token (|, >, <, ;, &, or backticks) is refused outright, since there is "
    "nothing here to interpret it - request the raw output of one command and work with it yourself "
    "instead of trying to chain commands together. For a 'how many' question, set count_lines to "
    "true instead of trying to pipe into wc -l. The user sees the exact command and your reason "
    "before deciding, and may say no."
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
PATH_DESCRIPTION = (
    "Optional target for commands that accept one: an absolute directory path, or a device path for "
    "drive-health commands. Omit it to use the command's default."
)
MAX_TOOL_ROUNDS = 4
# Nudges do not consume a tool round, so they need their own ceiling to bound the turn.
MAX_NUDGES = 2
MAX_TOOL_RETRIES = 2
MAX_TOKENS = 16000
_HTTP_TIMEOUT = 120.0

INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")

# Sent on the final round, where the tool schema is withheld. Withholding the tools is invisible to
# the model - nothing in the conversation says the budget is gone - so without this it keeps
# narrating its next step and never writes the report. That is the exact failure this prevents.
FINAL_ROUND_MESSAGE = (
    "You have used all of your tool rounds and cannot run any more commands. Answer now, from what "
    "you have already observed, with ONLY the <disk_report> XML and nothing else. If something could "
    "not be determined, say so in the explanation rather than asking to check further."
)

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

    Retries transient failures, because the alternative is handing the model an error string it will
    reason about as though the machine had actually reported that - a dropped loopback connection
    must not become a finding about the user's disk. Never raises: a failure that survives the
    retries becomes an error string, which is an honest answer the model can report."""
    params = {"path": path} if path else None
    url = f"{INTERNAL_API_BASE}/linux/tools/disk/{command_id}"

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
                    f"disk tool '{command_id}' returned {response.status_code}, retry {attempt + 1}"
                )
                await asyncio.sleep(transient_delay(attempt))
                continue

            response.raise_for_status()
            return response.json()["output"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            if attempt < MAX_TOOL_RETRIES:
                logger.warning(f"disk tool '{command_id}' failed ({e}), retry {attempt + 1}")
                await asyncio.sleep(transient_delay(attempt))
                continue
            return f"Error calling disk tool '{command_id}': {e}"

    return f"Error calling disk tool '{command_id}': exhausted {MAX_TOOL_RETRIES} retries"


async def _call_command_tool(request_id, argv, count_lines=False):
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


def _command_result(label, output):
    return {
        "type": "tool_result",
        "agent": "disk",
        "command": COMMAND_TOOL_NAME,
        "label": label,
        "path": None,
        "output": output,
    }


async def _run_command_request(argv, reason, count_lines=False):
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
        yield _command_result(label, f"That command cannot be run: {error}.")
        return

    request_id = permissions.create(argv, reason)
    yield {
        "type": "permission_request",
        "agent": "disk",
        "request_id": request_id,
        "command": label,
        "reason": (reason or "").strip(),
        "count_lines": count_lines,
    }

    try:
        approved = await permissions.wait(request_id)
        yield {
            "type": "permission_resolved",
            "agent": "disk",
            "request_id": request_id,
            "command": label,
            "approved": approved,
        }

        if not approved:
            yield _command_result(label, COMMAND_DECLINED)
            return

        yield {
            "type": "tool_call",
            "agent": "disk",
            "command": COMMAND_TOOL_NAME,
            "label": label,
            "path": None,
        }
        output = await _call_command_tool(request_id, argv, count_lines)
    finally:
        permissions.discard(request_id)

    yield _command_result(label, output)


async def _dispatch_tool(name, args):
    """Routes one tool call to its handler. Every path ends with a tool_result event carrying the
    output, so callers can collect it uniformly."""
    if name == COMMAND_TOOL_NAME:
        async for event in _run_command_request(
            args.get("argv"), args.get("reason"), args.get("count_lines")
        ):
            yield event
        return

    async for event in _run_tool(args.get("command"), args.get("path")):
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
            path=args.get("path"),
            output=output,
        )
    )


def _final_event(disk_report, thinking, commands_run):
    return {
        "type": "final",
        "mode": "disk",
        "thinking": thinking.strip() or None,
        "disk_report": disk_report.model_dump(),
        "commands_run": [cr.model_dump() for cr in commands_run],
    }


# Narration is the prose the model writes before its final answer; the answer itself is XML. The
# split is therefore at the first real tag, not at the first '<' - "less than 1 GB free" is prose a
# user wants to read, and cutting on the bare character silently truncated it.
_TAG_START_RE = re.compile(r"</?[A-Za-z]")


def _narration_prefix_len(buffered, complete=False):
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


def _narration_chunk(buffered, narrated, complete=False):
    """The slice of `buffered` not yet streamed, given `narrated` characters already sent."""
    limit = _narration_prefix_len(buffered, complete)
    if limit <= narrated:
        return "", narrated
    return buffered[narrated:limit], limit


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
                        "enum": list(DISK_COMMANDS.keys()),
                        "description": _command_enum_description(),
                    },
                    "path": {"type": "string", "description": PATH_DESCRIPTION},
                },
                "required": ["command"],
            },
        },
        {
            "name": COMMAND_TOOL_NAME,
            "description": COMMAND_TOOL_DESCRIPTION,
            "input_schema": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": ARGV_DESCRIPTION,
                    },
                    "reason": {"type": "string", "description": REASON_DESCRIPTION},
                    "count_lines": {"type": "boolean", "description": COUNT_LINES_DESCRIPTION},
                },
                "required": ["argv", "reason"],
            },
        },
    ]


async def _anthropic_round(client, model_id, messages, tools, result):
    kwargs = {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "system": DISK_AGENT_SYSTEM_PROMPT,
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

    yield _final_event(parse_disk_report(final_text), narration, commands_run)


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
                            "enum": list(DISK_COMMANDS.keys()),
                            "description": _command_enum_description(),
                        },
                        "path": {"type": "string", "description": PATH_DESCRIPTION},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": COMMAND_TOOL_NAME,
                "description": COMMAND_TOOL_DESCRIPTION,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": ARGV_DESCRIPTION,
                        },
                        "reason": {"type": "string", "description": REASON_DESCRIPTION},
                        "count_lines": {"type": "boolean", "description": COUNT_LINES_DESCRIPTION},
                    },
                    "required": ["argv", "reason"],
                },
            },
        },
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
        {"role": "system", "content": DISK_AGENT_SYSTEM_PROMPT},
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
        "functionDeclarations": [
            {
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
            },
            {
                "name": COMMAND_TOOL_NAME,
                "description": COMMAND_TOOL_DESCRIPTION,
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "argv": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": ARGV_DESCRIPTION,
                        },
                        "reason": {"type": "STRING", "description": REASON_DESCRIPTION},
                        "count_lines": {"type": "BOOLEAN", "description": COUNT_LINES_DESCRIPTION},
                    },
                    "required": ["argv", "reason"],
                },
            },
        ],
    }]


async def _gemini_round(url, api_key, contents, tools, result):
    payload = {
        "system_instruction": {"parts": [{"text": DISK_AGENT_SYSTEM_PROMPT}]},
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

    yield _final_event(parse_disk_report(final_text), narration, commands_run)


_AGENTS = {
    "anthropic": _run_anthropic,
    "openai": _run_openai,
    "gemini": _run_gemini,
    "groq": _run_groq,
}


async def run_disk_agent(provider, api_key, model_id, message):
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
        logger.exception("disk agent failed")
        if not saw_terminal:
            yield {"type": "error", "status": 502, "detail": f"disk agent failed: {e}"}
        return

    if not saw_terminal:
        logger.error("disk agent finished without a terminal event")
        yield {"type": "error", "status": 502, "detail": "disk agent produced no result"}
