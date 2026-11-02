import random

import pytest

from tests.fakes import FakeProvider, call, resp
from whippletree import pricing
from whippletree.case import Case, Range
from whippletree.loop import Counters
from whippletree.runner import cost_for, run_baseline, run_review
from whippletree.traces import TraceWriter, read_trace

FINDING = {"file": "a.py", "line": 1, "claim": "bug", "confidence": 0.9}


@pytest.fixture
def case(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    return Case(id="t/1", dataset="t", checkout_path=tmp_path,
                diff="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n",
                ground_truth=(Range("a.py", 1, 1),))


def test_run_review_writes_calls_and_cases(case, tmp_path):
    provider = FakeProvider([
        resp(calls=[call("submit_findings", {"findings": [FINDING]})], cost=0.002),
        resp(calls=[call("submit_findings", {"findings": []})], cost=0.002),
    ])
    path = tmp_path / "run.jsonl"
    with TraceWriter(path) as trace:
        records = run_review([case], "openrouter:x/y", provider, trace, repeat=2)
    assert [r.repeat for r in records] == [0, 1]
    assert records[0].findings[0].line == 1
    assert (records[0].cost_usd, records[0].cost_source) == (0.002, "provider")
    kinds = [e["kind"] for e in read_trace(path)]
    assert kinds == ["call", "case", "call", "case"]


def test_run_baseline_records(case, tmp_path):
    with TraceWriter(tmp_path / "b.jsonl") as trace:
        records = run_baseline([case], 3, random.Random(0), trace)
    assert records[0].cost_usd == 0.0
    assert records[0].findings  # guessed at least one changed line


def test_cost_for_prefers_provider_cost():
    c = Counters(steps=2, cost_usd=0.5, cost_reported_calls=2)
    assert cost_for("openrouter:x/y", c) == (0.5, "provider")


def test_cost_for_falls_back_to_table(monkeypatch):
    monkeypatch.setitem(pricing.PRICES, "openrouter:x/y", (1.0, 2.0))
    c = Counters(steps=1, input_tokens=1_000_000, output_tokens=0)
    assert cost_for("openrouter:x/y", c) == (1.0, "table")
    assert cost_for("openrouter:other/z", c) == (None, "unknown")


def test_cost_for_no_calls_is_free():
    assert cost_for("openrouter:x/y", Counters()) == (0.0, "none")


def test_case_event_has_transcript(case, tmp_path):
    provider = FakeProvider([resp(calls=[call("submit_findings", {"findings": []})])])
    path = tmp_path / "t.jsonl"
    with TraceWriter(path) as trace:
        run_review([case], "ollama:x", provider, trace)
    event = [e for e in read_trace(path) if e["kind"] == "case"][0]
    assert event["transcript"][0]["role"] == "system"
    assert "reviewing a pull request" in event["transcript"][0]["content"]


def test_cost_for_free_provider_is_labelled_free():
    c = Counters(steps=1, input_tokens=100, output_tokens=10)
    assert cost_for("ollama:llama3.1:8b", c) == (0.0, "free")


def test_one_failing_case_does_not_sink_the_run(tmp_path):
    cases = []
    for name in ("one", "two"):
        d = tmp_path / name
        d.mkdir()
        (d / "a.py").write_text("x = 1\n")
        cases.append(Case(id=f"t/{name}", dataset="t", checkout_path=d, diff="",
                          ground_truth=(Range("a.py", 1, 1),)))
    provider = FakeProvider([
        RuntimeError("boom"),
        resp(calls=[call("submit_findings", {"findings": [FINDING]})]),
    ])
    path = tmp_path / "run.jsonl"
    with TraceWriter(path) as trace:
        records = run_review(cases, "ollama:x", provider, trace)
        trace.write("end", cases=len(records))
    bad, good = records
    assert (bad.stop, bad.errored, bad.findings) == ("error", True, ())
    assert (bad.cost_usd, bad.cost_source) == (0.0, "none")
    assert good.stop == "done" and not good.errored
    events = read_trace(path)
    case_events = [e for e in events if e["kind"] == "case"]
    assert case_events[0]["error"] == "RuntimeError('boom')"
    assert events[-1]["kind"] == "end"
