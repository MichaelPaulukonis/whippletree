"""Score findings against ground truth. Pure functions, no I/O.

Errored cases (record.errored, set by the runner) are excluded from precision and
recall but still counted in cost and tokens. A metric with no data is None, not 0.0.
"""

from collections import defaultdict
from dataclasses import dataclass

from whippletree.case import Finding, Range

DEFAULT_WINDOW = 5
DEFAULT_THRESHOLDS = (0.0, 0.5, 0.7, 0.9)


@dataclass(frozen=True)
class CaseScore:
    tp: int  # ground-truth ranges hit
    fp: int  # findings that hit nothing
    dupes: int  # extra findings on an already-hit range
    hit: tuple[bool, ...]  # per range

    @property
    def found(self) -> bool:
        """All ranges in a case are one bug: found if any range was hit."""
        return any(self.hit)


def same_file(found: str, truth: str) -> bool:
    name = found.strip().removeprefix("./").removeprefix("/")
    return name in (truth, f"a/{truth}", f"b/{truth}")


def score(findings, truth: tuple[Range, ...], window: int = DEFAULT_WINDOW) -> CaseScore:
    hit = [False] * len(truth)
    tp = fp = dupes = 0
    for finding in findings:
        near = [i for i, r in enumerate(truth)
                if same_file(finding.file, r.file) and r.start - window <= finding.line <= r.end + window]
        # Prefer a range not yet hit, so two close bugs both count.
        idx = next((i for i in near if not hit[i]), near[0] if near else None)
        if idx is None:
            fp += 1
        elif hit[idx]:
            dupes += 1
        else:
            hit[idx] = True
            tp += 1
    return CaseScore(tp, fp, dupes, tuple(hit))


@dataclass(frozen=True)
class CaseRecord:
    """One reviewed case, as written to the trace and read back by report."""

    case_id: str
    repeat: int
    findings: tuple[Finding, ...]
    truth: tuple[Range, ...]
    stop: str
    tokens: int
    cost_usd: float | None
    cost_source: str
    tool_errors: int
    parse_failures: int
    errored: bool

    @classmethod
    def from_dict(cls, d: dict) -> "CaseRecord":
        return cls(
            case_id=d["case_id"],
            repeat=d["repeat"],
            findings=tuple(Finding(**x) for x in d["findings"]),
            truth=tuple(Range(**x) for x in d["truth"]),
            stop=d["stop"],
            tokens=d["tokens"],
            cost_usd=d["cost_usd"],
            cost_source=d["cost_source"],
            tool_errors=d["tool_errors"],
            parse_failures=d["parse_failures"],
            errored=d["errored"],
        )


@dataclass(frozen=True)
class RunMetrics:
    """None means undefined (no findings, or no non-errored cases), not zero.
    Exception: f1 is 0.0 when recall is 0.0, so a run that found nothing sorts last.

    cost_per_tp and tokens_per_tp divide by found cases: a case counts once
    however many of its ranges were hit.
    """

    cases: int
    errored: int
    recall: float | None  # share of cases whose bug was found
    precision: float | None  # share of findings that hit a bug (dupes count as hits)
    f1: float | None
    cost_usd: float | None
    cost_per_tp: float | None  # per found case
    tokens_per_tp: float | None  # per found case
    tool_errors: int
    parse_failures: int
    recall_by_kind: dict[str, float]
    pr_curve: list[tuple[float, float | None, float | None]]  # (threshold, precision, recall)


def case_kind(truth: tuple[Range, ...]) -> str:
    kinds = {r.kind for r in truth}
    if not kinds:
        return "none"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def aggregate(records, window: int = DEFAULT_WINDOW,
              thresholds=DEFAULT_THRESHOLDS) -> RunMetrics:
    ok = [r for r in records if not r.errored]

    def at(threshold: float) -> tuple[float | None, float | None, int]:
        hits = fps = found = 0
        for r in ok:
            s = score([x for x in r.findings if x.confidence >= threshold], r.truth, window)
            hits += s.tp + s.dupes
            fps += s.fp
            found += s.found
        precision = hits / (hits + fps) if hits + fps else None
        recall = found / len(ok) if ok else None
        return precision, recall, found

    precision, recall, found = at(0.0)
    if recall is None:
        f1 = None
    elif not recall or not precision:
        f1 = 0.0  # found nothing (or only misses): sorts to the bottom, not undefined
    else:
        f1 = 2 * precision * recall / (precision + recall)
    costs = [r.cost_usd for r in records]
    cost = None if any(c is None for c in costs) else sum(costs)
    tokens = sum(r.tokens for r in records)

    by_kind: dict[str, list[bool]] = defaultdict(list)
    for r in ok:
        by_kind[case_kind(r.truth)].append(score(r.findings, r.truth, window).found)

    return RunMetrics(
        cases=len(ok),
        errored=len(records) - len(ok),
        recall=recall,
        precision=precision,
        f1=f1,
        cost_usd=cost,
        cost_per_tp=cost / found if cost is not None and found else None,
        tokens_per_tp=tokens / found if found else None,
        tool_errors=sum(r.tool_errors for r in records),
        parse_failures=sum(r.parse_failures for r in records),
        recall_by_kind={k: sum(v) / len(v) for k, v in by_kind.items()},
        pr_curve=[(t, *at(t)[:2]) for t in thresholds],
    )
