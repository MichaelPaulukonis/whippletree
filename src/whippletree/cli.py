"""whippletree run review|baseline, whippletree report."""

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from whippletree import __version__
from whippletree.datasets.seeded import load_seeded
from whippletree.loop import Limits
from whippletree.providers.base import ProviderError, parse_model
from whippletree.providers.openai_compat import OpenAICompatProvider
from whippletree.roles.reviewer import build_system_prompt
from whippletree.runner import run_baseline, run_review
from whippletree.scoring import (
    DEFAULT_THRESHOLDS,
    DEFAULT_WINDOW,
    CaseRecord,
    RunMetrics,
    aggregate,
)
from whippletree.traces import TraceWriter, new_run_id, read_trace

DATASETS = ("seeded",)
SETTINGS = {"temperature": 0}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader. Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip("'\""))


def make_provider(model_spec: str, routing: list[str] | None):
    name, _ = parse_model(model_spec)
    return OpenAICompatProvider(name, routing=routing)


def _git(*args: str) -> str | None:
    """Run git in the whippletree checkout (not the process cwd); None on failure."""
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).resolve().parent)
        return proc.stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def git_sha() -> str:
    out = _git("rev-parse", "HEAD")
    return out.strip() if out is not None else "unknown"


def git_dirty() -> bool:
    out = _git("status", "--porcelain")
    return bool(out and out.strip())


def dataset_hash(cases) -> str:
    """sha256 over the cases' id, diff and ground truth, sorted by id."""
    payload = [{"id": c.id, "diff": c.diff, "truth": [asdict(r) for r in c.ground_truth]}
               for c in sorted(cases, key=lambda c: c.id)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


def load_cases(dataset: str, case_id: str | None, limit: int | None):
    cases = load_seeded() if dataset == "seeded" else []
    if case_id:
        cases = [c for c in cases if c.id == case_id]
    return cases[:limit] if limit is not None else cases


def select_cases(args, case_id: str | None):
    cases = load_cases(args.dataset, case_id, args.limit)
    if not cases:
        raise ValueError(f"no cases match dataset={args.dataset} case={case_id} "
                         f"limit={args.limit}")
    return cases


def _base_header(args, cases, case_id: str | None) -> dict:
    return dict(
        dataset=args.dataset, git_sha=git_sha(), git_dirty=git_dirty(), version=__version__,
        argv=args.argv, case_filter=case_id, limit=args.limit,
        dataset_hash=dataset_hash(cases), window=DEFAULT_WINDOW,
        thresholds=DEFAULT_THRESHOLDS,
    )


def _trace_path(runs_dir: str, run_id: str) -> Path:
    return Path(runs_dir) / f"{run_id}.jsonl"


def cmd_review(args) -> int:
    cases = select_cases(args, args.case)
    routing = args.routing.split(",") if args.routing else None
    provider = make_provider(args.model, routing)
    limits = Limits()
    run_id = new_run_id()
    with TraceWriter(_trace_path(args.runs_dir, run_id)) as trace:
        trace.write("header", run_id=run_id, mode="review", model=args.model,
                    limits=limits, settings=SETTINGS, routing=routing, repeat=args.repeat,
                    prompt_sha=hashlib.sha256(build_system_prompt(limits).encode()).hexdigest(),
                    **_base_header(args, cases, args.case))
        records = run_review(cases, args.model, provider, trace, limits=limits,
                             settings=SETTINGS, repeat=args.repeat)
        trace.write("end", cases=len(records))
    print(run_id)
    return 0


def cmd_baseline(args) -> int:
    cases = select_cases(args, None)
    run_id = new_run_id()
    with TraceWriter(_trace_path(args.runs_dir, run_id)) as trace:
        trace.write("header", run_id=run_id, mode="baseline", model=f"baseline:{args.strategy}",
                    k=args.k, seed=args.seed, **_base_header(args, cases, None))
        records = run_baseline(cases, args.k, random.Random(args.seed), trace)
        trace.write("end", cases=len(records))
    print(run_id)
    return 0


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.4f}"


def _num(x: float | None) -> str:
    """Undefined metrics (None) render as '-'."""
    return "-" if x is None else f"{x:.2f}"


def format_metrics(run_id: str, header: dict, m: RunMetrics, served_by: list[str],
                   records: list[CaseRecord], complete: bool = True) -> str:
    tokens = "n/a" if m.tokens_per_tp is None else f"{m.tokens_per_tp:.0f}"
    kinds = ", ".join(f"{k} {v:.2f}" for k, v in sorted(m.recall_by_kind.items())) or "-"
    curve = " | ".join(f">={t:.1f} P{_num(p)} R{_num(r)}" for t, p, r in m.pr_curve)
    stops = ", ".join(f"{s} {n}" for s, n in sorted(Counter(r.stop for r in records).items()))
    n_cases = len({r.case_id for r in records})
    repeats = sorted({r.repeat for r in records})
    cases_label = (f"cases {n_cases} x {len(repeats)} repeats (errored {m.errored})"
                   if len(repeats) > 1 else f"cases {m.cases} (errored {m.errored})")
    sources = ", ".join(f"{s} {n}" for s, n in
                        sorted(Counter(r.cost_source for r in records).items()))
    lines = [
        f"run {run_id}  model={header['model']}  dataset={header['dataset']}  "
        f"served_by={','.join(served_by) or '-'}",
        f"  {cases_label}  recall {_num(m.recall)}  "
        f"precision {_num(m.precision)}  F1 {_num(m.f1)}",
        f"  cost {_money(m.cost_usd)}  $/found {_money(m.cost_per_tp)}  tokens/found {tokens}",
        f"  cost sources: {sources or '-'}",
        f"  tool_errors {m.tool_errors}  parse_failures {m.parse_failures}",
        f"  stops: {stops or '-'}",
        f"  recall by kind: {kinds}",
        f"  PR curve: {curve}",
    ]
    if len(repeats) > 1:
        per = [aggregate([r for r in records if r.repeat == k]).recall for k in repeats]
        defined = [x for x in per if x is not None]
        spread = _num(max(defined) - min(defined)) if defined else "-"
        lines.append(f"  recall per repeat: {', '.join(_num(x) for x in per)} "
                     f"(spread {spread})")
    if len(served_by) > 1:
        lines.append("  WARNING: served by more than one backend; numbers mix providers")
    if not complete:
        lines.append("  WARNING: incomplete run (no end event)")
    return "\n".join(lines)


def cmd_report(args) -> int:
    blocks = []
    for run_id in args.run_ids:
        events = read_trace(_trace_path(args.runs_dir, run_id))
        header = next((e for e in events if e["kind"] == "header"), None)
        if header is None:
            raise ValueError(f"trace for run {run_id} has no header event")
        records = [CaseRecord.from_dict(e["record"]) for e in events if e["kind"] == "case"]
        served = sorted({e["served_by"] for e in events
                         if e["kind"] == "call" and e.get("served_by")})
        blocks.append(format_metrics(run_id, header, aggregate(records), served, records,
                                    complete=any(e["kind"] == "end" for e in events)))
    print("\n\n".join(blocks))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whippletree")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a benchmark")
    modes = run.add_subparsers(dest="mode", required=True)

    review = modes.add_parser("review", help="run a reviewer model over a dataset")
    review.add_argument("--dataset", choices=DATASETS, required=True)
    review.add_argument("--model", required=True, help="provider:model-id")
    review.add_argument("--limit", type=positive_int)
    review.add_argument("--repeat", type=positive_int, default=1)
    review.add_argument("--case", help="run one case by id")
    review.add_argument("--routing", help="OpenRouter backends to pin, comma-separated")
    review.add_argument("--runs-dir", default="runs")
    review.set_defaults(func=cmd_review)

    baseline = modes.add_parser("baseline", help="run the random-guess baseline")
    baseline.add_argument("--dataset", choices=DATASETS, required=True)
    baseline.add_argument("--strategy", choices=("random",), default="random")
    baseline.add_argument("--k", type=positive_int, default=3, help="guesses per case")
    baseline.add_argument("--seed", type=int, default=0)
    baseline.add_argument("--limit", type=positive_int)
    baseline.add_argument("--runs-dir", default="runs")
    baseline.set_defaults(func=cmd_baseline)

    report = sub.add_parser("report", help="print metrics for one or more runs")
    report.add_argument("run_ids", nargs="+")
    report.add_argument("--runs-dir", default="runs")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    args.argv = list(argv) if argv is not None else sys.argv[1:]
    try:
        return args.func(args)
    except (FileNotFoundError, ProviderError, ValueError) as e:
        print(f"whippletree: {e}", file=sys.stderr)
        return 2
