"""The agent loop: call the model, run the tools it asks for, repeat.

Flat and single-agent. It knows nothing about roles, datasets, or where tools
execute. Messages use the OpenAI chat format.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from whippletree.providers.base import Provider, ProviderError, Response, TransientError
from whippletree.tools.base import Submit, Tool, ToolError

# {tool} is filled with the terminal tool name(s) at run time; the loop knows no role's tools.
NUDGE = "You have not submitted. Call {tool} to complete your task."
WARNING = "Limit almost reached: call {tool} now with what you have."
WARN_AT_BUDGET_SHARE = 0.8
NOT_RUN = "not run: time limit reached"

_NOTHING = object()


@dataclass(frozen=True)
class Limits:
    max_steps: int = 20
    token_budget: int = 200_000
    wall_clock_s: float = 300.0
    max_tool_output_bytes: int = 20_000
    max_retries: int = 3


@dataclass
class Counters:
    steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    errors_by_tool: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    truncated_bytes: int = 0
    nudges: int = 0
    warnings: int = 0
    truncated_outputs: int = 0  # responses cut off by the model's max output length
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_reported_calls: int = 0


@dataclass
class LoopResult:
    result: Any
    transcript: list[dict]
    stop: str  # done | no_submit | max_steps | budget | timeout | error
    counters: Counters
    error: str | None = None


def run(
    provider: Provider,
    model: str,
    messages: list[dict],
    tools: list[Tool],
    limits: Limits | None = None,
    settings: dict | None = None,
    nudge: str | None = NUDGE,
    warning: str | None = WARNING,
    on_call: Callable[[dict], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> LoopResult:
    limits = limits or Limits()
    transcript = list(messages)
    by_name = {t.name: t for t in tools}
    schemas = [t.schema() for t in tools]
    terminal_names = [t.name for t in tools if t.terminal]
    has_terminal = bool(terminal_names)
    names = " or ".join(terminal_names)
    nudge = nudge.replace("{tool}", names) if nudge else nudge
    warning = warning.replace("{tool}", names) if warning else warning
    c = Counters()
    started = clock()
    slept = [0.0]  # retry backoff is the harness's time, not the model's

    def timed_sleep(seconds):
        slept[0] += seconds
        sleep(seconds)

    def elapsed(now):
        return now - started - slept[0]

    def finish(stop, result=None, error=None):
        return LoopResult(result, transcript, stop, c, error)

    while True:
        if c.steps >= limits.max_steps:
            return finish("max_steps")
        if elapsed(clock()) > limits.wall_clock_s:
            return finish("timeout")
        tokens = c.input_tokens + c.output_tokens
        if warning and has_terminal and c.warnings < 1 and (
            c.steps == limits.max_steps - 1
            or tokens >= WARN_AT_BUDGET_SHARE * limits.token_budget
        ):
            c.warnings += 1
            transcript.append({"role": "user", "content": warning})

        t0 = clock()
        try:
            resp = _call_with_retry(provider, transcript, schemas, model, settings or {}, limits,
                                    c, timed_sleep)
        except ProviderError as e:
            return finish("error", error=str(e))
        now = clock()
        latency = now - t0
        _account(c, resp)
        if on_call:
            on_call({
                "step": c.steps,
                "latency_s": round(latency, 3),
                "usage": asdict(resp.usage),
                "cost_usd": resp.cost_usd,
                "served_by": resp.served_by,
                "stop_reason": resp.stop_reason,
                "tool_calls": [tc.name for tc in resp.tool_calls],
            })
        transcript.append(_assistant_message(resp))
        over_budget = c.input_tokens + c.output_tokens > limits.token_budget
        out_of_time = elapsed(now) > limits.wall_clock_s
        cut_off = resp.stop_reason == "length"

        if not resp.tool_calls:
            if not has_terminal:
                return finish("done", result=resp.text)
            if over_budget:
                return finish("budget")
            if out_of_time:
                return finish("timeout")
            if nudge and c.nudges < 1:
                c.nudges += 1
                transcript.append({"role": "user", "content": nudge})
                continue
            return finish("no_submit")

        # Out of time: only a response that tries to submit is worth dispatching.
        if out_of_time and not any(
            tc.name in by_name and by_name[tc.name].terminal for tc in resp.tool_calls
        ):
            # Answer every call so the transcript stays a valid conversation to replay.
            for tc in resp.tool_calls:
                transcript.append({"role": "tool", "tool_call_id": tc.id, "content": NOT_RUN})
            return finish("timeout")

        # Every tool call must get a result message, even after a successful submit.
        submitted = _NOTHING
        for tc in resp.tool_calls:
            c.tool_calls += 1
            output, value = _dispatch(by_name, tc, c, cut_off)
            transcript.append(
                {"role": "tool", "tool_call_id": tc.id, "content": _truncate(output, limits, c)}
            )
            if value is not _NOTHING and submitted is _NOTHING:
                submitted = value
        if submitted is not _NOTHING:
            return finish("done", result=submitted)
        if over_budget:
            return finish("budget")
        if out_of_time:
            return finish("timeout")


def _call_with_retry(provider, transcript, schemas, model, settings, limits, c, sleep) -> Response:
    for attempt in range(limits.max_retries + 1):
        try:
            return provider.complete(transcript, schemas, model, settings)
        except TransientError as e:
            if attempt == limits.max_retries:
                raise ProviderError(f"gave up after {attempt} retries: {e}") from e
            c.retries += 1
            sleep(2**attempt)
    raise AssertionError("unreachable")


def _account(c: Counters, resp: Response) -> None:
    c.steps += 1
    if resp.stop_reason == "length":
        c.truncated_outputs += 1
    c.input_tokens += resp.usage.input
    c.output_tokens += resp.usage.output
    c.cached_tokens += resp.usage.cached
    if resp.cost_usd is not None:
        c.cost_usd += resp.cost_usd
        c.cost_reported_calls += 1


def _assistant_message(resp: Response) -> dict:
    """Provider extras (e.g. reasoning_details) ride along; some backends require them back."""
    if not resp.tool_calls:
        return {**resp.extra, "role": "assistant", "content": resp.text}
    return {
        **resp.extra,
        "role": "assistant",
        "content": resp.text or None,
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in resp.tool_calls
        ],
    }


def _dispatch(by_name: dict, tc, c: Counters, cut_off: bool = False):
    tool = by_name.get(tc.name)
    try:
        if tool is None:
            raise ToolError(f"unknown tool: {tc.name}")
        try:
            args = json.loads(tc.arguments or "{}")
        except json.JSONDecodeError as e:
            why = " (your output was cut off by the model's max output length)" if cut_off else ""
            raise ToolError(f"arguments are not valid JSON{why}: {e}") from e
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        out = tool.fn(args)
    except ToolError as e:
        c.tool_errors += 1
        c.errors_by_tool[tc.name] = c.errors_by_tool.get(tc.name, 0) + 1
        return f"ERROR: {e}", _NOTHING
    if isinstance(out, Submit):
        return "submitted", out.value
    return out, _NOTHING


def _truncate(text: str, limits: Limits, c: Counters) -> str:
    data = text.encode()
    if len(data) <= limits.max_tool_output_bytes:
        return text
    cut = len(data) - limits.max_tool_output_bytes
    c.truncated_bytes += cut
    kept = data[: limits.max_tool_output_bytes].decode(errors="ignore")
    return f"{kept}\n[truncated {cut} bytes]"
