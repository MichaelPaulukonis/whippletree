import itertools

from tests.fakes import FakeProvider, call, resp
from whippletree.loop import NUDGE, Limits, run
from whippletree.providers.base import ProviderError, ToolCall, TransientError
from whippletree.tools.base import Submit, Tool, ToolError

OBJ = {"type": "object", "properties": {}}
echo = Tool("echo", "echo", OBJ, fn=lambda a: f"echo {a.get('x')}")
big = Tool("big", "big", OBJ, fn=lambda a: "x" * 50)


def _submit(args):
    if "v" not in args:
        raise ToolError("need v")
    return Submit(args["v"])


submit = Tool("submit", "submit", OBJ, fn=_submit, terminal=True)
MSGS = [{"role": "user", "content": "go"}]


def go(script, tools, limits=None, **kw):
    provider = FakeProvider(script)
    kw.setdefault("sleep", lambda s: None)
    return provider, run(provider, "m", MSGS, tools, limits=limits, **kw)


def test_without_terminal_tool_a_text_reply_is_done():
    _, r = go([resp("hi")], [echo])
    assert (r.stop, r.result) == ("done", "hi")


def test_terminal_tool_success_stops_with_its_value():
    _, r = go([resp(calls=[call("echo", {"x": 1})]), resp(calls=[call("submit", {"v": [1]})])],
              [echo, submit])
    assert (r.stop, r.result) == ("done", [1])
    assert (r.counters.steps, r.counters.tool_calls) == (2, 2)
    assert {"role": "tool", "tool_call_id": "c1", "content": "echo 1"} in r.transcript


def test_failed_terminal_call_goes_back_to_model_for_retry():
    p, r = go([resp(calls=[call("submit", {})]), resp(calls=[call("submit", {"v": 2})])], [submit])
    assert (r.stop, r.result) == ("done", 2)
    assert r.counters.tool_errors == 1
    assert r.counters.errors_by_tool == {"submit": 1}
    assert p.seen[1][-1]["content"] == "ERROR: need v"


def test_unknown_tool_and_bad_json_are_tool_errors():
    bad = resp(calls=[ToolCall("c1", "nope", "{}"), ToolCall("c2", "echo", "{not json")])
    _, r = go([bad, resp(calls=[call("submit", {"v": 0})])], [echo, submit])
    assert r.stop == "done"
    assert r.counters.tool_errors == 2
    tool_msgs = [m for m in r.transcript if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("ERROR: unknown tool")
    assert tool_msgs[1]["content"].startswith("ERROR: arguments are not valid JSON")


def test_no_tool_calls_nudges_once_then_no_submit():
    p, r = go([resp("done?"), resp("really done")], [echo, submit])
    assert r.stop == "no_submit"
    assert r.result is None
    assert r.counters.nudges == 1
    assert p.seen[1][-1] == {"role": "user", "content": NUDGE}


def test_nudge_then_submit_is_done():
    _, r = go([resp("done?"), resp(calls=[call("submit", {"v": "ok"})])], [submit])
    assert (r.stop, r.result, r.counters.nudges) == ("done", "ok", 1)


def test_max_steps():
    script = [resp(calls=[call("echo", {})]) for _ in range(3)]
    _, r = go(script, [echo, submit], Limits(max_steps=2))
    assert (r.stop, r.counters.steps) == ("max_steps", 2)


def test_token_budget():
    script = [resp(calls=[call("echo", {})]) for _ in range(3)]  # 15 tokens each
    _, r = go(script, [echo, submit], Limits(token_budget=25))
    assert (r.stop, r.counters.steps) == ("budget", 2)


def test_budget_never_discards_a_submission():
    _, r = go([resp(calls=[call("submit", {"v": 1})])], [submit], Limits(token_budget=5))
    assert (r.stop, r.result) == ("done", 1)


def test_wall_clock_timeout():
    clock = itertools.count(0, 200).__next__  # each clock() call advances 200s
    _, r = go([resp(calls=[call("echo", {})])], [echo, submit], Limits(wall_clock_s=300),
              clock=clock)
    assert (r.stop, r.counters.steps) == ("timeout", 1)


def test_transient_errors_are_retried_with_backoff():
    sleeps = []
    _, r = go([TransientError("429"), TransientError("503"), resp("ok")], [echo],
              sleep=sleeps.append)
    assert (r.stop, r.result) == ("done", "ok")
    assert r.counters.retries == 2
    assert sleeps == [1, 2]


def test_retries_exhausted_is_error():
    _, r = go([TransientError("429"), TransientError("429")], [echo], Limits(max_retries=1))
    assert r.stop == "error"
    assert "gave up" in r.error


def test_permanent_error_is_not_retried():
    _, r = go([ProviderError("400 bad request")], [echo])
    assert (r.stop, r.counters.retries) == ("error", 0)


def test_tool_output_is_truncated():
    _, r = go([resp(calls=[call("big", {})]), resp(calls=[call("submit", {"v": 1})])],
              [big, submit], Limits(max_tool_output_bytes=10))
    content = next(m["content"] for m in r.transcript if m["role"] == "tool")
    assert content == "x" * 10 + "\n[truncated 40 bytes]"
    assert r.counters.truncated_bytes == 40


def test_tokens_and_reported_cost_are_counted():
    script = [resp(calls=[call("echo", {})], cost=0.01), resp(calls=[call("submit", {"v": 1})],
                                                              cost=0.01)]
    _, r = go(script, [echo, submit])
    c = r.counters
    assert (c.input_tokens, c.output_tokens) == (20, 10)
    assert round(c.cost_usd, 6) == 0.02
    assert c.cost_reported_calls == 2


def test_on_call_gets_one_event_per_model_call():
    events = []
    go([resp(calls=[call("echo", {})], served_by="Google"), resp(calls=[call("submit", {"v": 1})])],
       [echo, submit], on_call=events.append)
    assert [e["step"] for e in events] == [1, 2]
    assert events[0]["served_by"] == "Google"
    assert events[0]["tool_calls"] == ["echo"]
    assert events[0]["usage"] == {"input": 10, "output": 5, "cached": 0}


def test_every_tool_call_gets_a_result_even_after_submit():
    both = resp(calls=[call("submit", {"v": 1}, id="a"), call("echo", {}, id="b")])
    _, r = go([both], [echo, submit])
    assert r.stop == "done"
    assert [m["tool_call_id"] for m in r.transcript if m["role"] == "tool"] == ["a", "b"]
