"""Run a reviewer (or the baseline) over cases, writing the trace as it goes."""

import random

from whippletree.baseline import baseline_findings
from whippletree.case import Case
from whippletree.loop import Counters, Limits
from whippletree.pricing import estimate
from whippletree.providers.base import Provider, parse_model
from whippletree.roles.reviewer import review
from whippletree.scoring import CaseRecord
from whippletree.traces import TraceWriter

# Harness/provider failures, not model misses: excluded from precision and recall.
ERRORED_STOPS = ("error", "timeout")


def cost_for(model_spec: str, c: Counters) -> tuple[float | None, str]:
    if c.steps == 0:
        return 0.0, "none"
    if c.cost_reported_calls == c.steps:
        return c.cost_usd, "provider"
    est = estimate(model_spec, c.input_tokens, c.output_tokens)
    return (est, "table") if est is not None else (None, "unknown")


def run_review(
    cases: list[Case],
    model_spec: str,
    provider: Provider,
    trace: TraceWriter,
    limits: Limits | None = None,
    settings: dict | None = None,
    repeat: int = 1,
) -> list[CaseRecord]:
    _, model = parse_model(model_spec)
    records = []
    for rep in range(repeat):
        for case in cases:
            def on_call(event, case_id=case.id, rep=rep):
                trace.write("call", case_id=case_id, repeat=rep, **event)

            result = review(case, provider, model, limits=limits, settings=settings,
                            on_call=on_call)
            c = result.loop.counters
            cost, source = cost_for(model_spec, c)
            record = CaseRecord(
                case_id=case.id,
                repeat=rep,
                findings=tuple(result.findings),
                truth=case.ground_truth,
                stop=result.loop.stop,
                tokens=c.input_tokens + c.output_tokens,
                cost_usd=cost,
                cost_source=source,
                tool_errors=c.tool_errors,
                parse_failures=result.parse_failures,
                errored=result.loop.stop in ERRORED_STOPS,
            )
            trace.write("case", record=record, counters=c, padding=case.padding,
                        error=result.loop.error)
            records.append(record)
    return records


def run_baseline(cases: list[Case], k: int, rng: random.Random,
                 trace: TraceWriter) -> list[CaseRecord]:
    records = []
    for case in cases:
        record = CaseRecord(
            case_id=case.id,
            repeat=0,
            findings=tuple(baseline_findings(case, k, rng)),
            truth=case.ground_truth,
            stop="done",
            tokens=0,
            cost_usd=0.0,
            cost_source="none",
            tool_errors=0,
            parse_failures=0,
            errored=False,
        )
        trace.write("case", record=record, padding=case.padding)
        records.append(record)
    return records
