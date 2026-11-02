# Whippletree - Design Spec

Date: 2026-11-01
Status: approved in brainstorm, pending written-spec review
Scope of this spec: **Milestone 1, v0** (read-only review benchmark). Later phases are listed for context only and get their own specs.

A whippletree is the crossbar that balances the pull between several horses hitched to one load. Here the horses are models.

## Purpose

Whippletree is a public, self-built Python coding-agent harness. It exists to learn agent harnesses from the inside and to produce measured, chartable results for a staff-level agentic-coding pitch.

### Goal once measured

1. **Primary success criterion:** choose a personal code-review policy on evidence - "Claude writes; reviewer X at confidence >= T reviews; costs $Y per PR; catches Z% of bugs." The winning setup is then wired into daily work as a Claude Code skill.
2. A public repo plus one write-up with charts. Honest failures included.
3. Firsthand stories of how harnesses break (tool-call flakiness, routing drift, budget cutoffs).

### Hypotheses

- **H1:** a cheap model plus a verifier reaches >= 80% of Opus's recall at <= 20% of its cost. (Needs phase 1b, the verifier.)
- **H2:** cross-model review catches bugs that self-review misses. Not testable in M1 (BugsInPy bugs are human-written); needs M2 or a collected set of real Claude-made bugs.
- **H3:** native provider adapters cut cost >= X% vs OpenRouter (prompt caching). X is set after the phase 1a OpenRouter baseline.

v0 itself tests none of these directly; it produces the read-only baseline every hypothesis is compared against.

## Roadmap (context)

| Phase | What | Spec |
| --- | --- | --- |
| **1a (this spec)** | Read-only reviewer, OpenRouter + Ollama, BugsInPy + seeded, scoring, traces | this doc |
| 1b | Docker sandbox per bug, `run_tests` tool, network off (verifier) | separate |
| 1c | Native `anthropic` + `google-genai` adapters, benchmarked vs OpenRouter | separate |
| 2 | Coder -> test-writer -> reviewer pipeline on SWE-bench Verified subset | separate |
| later | Context management / token budgets (C); safety and permissions (D); optional REPL | separate |

## Decisions

- **Language:** Python 3.13, `uv` project.
- **Mode:** headless task runner. No REPL in v0.
- **Providers (1a):** everything through the `openai` SDK - OpenRouter (`https://openrouter.ai/api/v1`) and Ollama (`http://localhost:11434/v1`). No LiteLLM (2026 supply-chain compromises and CVEs), no Vercel AI SDK (TypeScript-only, and abstracts away the provider differences under study).
- **Dependencies:** minimal and pinned via `uv.lock`. Runtime: `openai` only. CLI via stdlib `argparse`; data structures via `dataclasses`. Dev: `pytest`, `ruff`.
- **Datasets:** BugsInPy for M1, plus ~10 hand-seeded bugs as a contamination-free control.
- **Execution:** none in v0. The reviewer reads only.

## Architecture

```
whippletree/
  src/whippletree/
    providers/
      base.py            Provider protocol, Message, ToolCall, Usage, Response
      openai_compat.py   OpenRouter + Ollama
    loop.py              agent loop
    tools/
      fs.py              read_file, list_dir, grep (confined to case checkout)
    roles/
      reviewer.py        system prompt, findings schema, parsing + repair
    datasets/
      base.py            Case, GroundTruth
      bugsinpy.py
      seeded.py
    scoring.py
    traces.py            JSONL writer
    pricing.py           local price table (fallback when provider gives no cost)
    cli.py
  tests/
  datasets/seeded/       hand-seeded cases (committed)
  results/               curated run summaries (committed)
  runs/                  raw traces (gitignored)
```

### Units and interfaces

**providers** - `complete(messages, tools, model, settings) -> Response`.
`Response = {text, tool_calls: list[ToolCall], usage: Usage{input, output, cached}, cost_usd | None, stop_reason, served_by | None, raw}`.
Knows nothing about the loop or datasets. Model strings are `provider:model-id` (e.g. `openrouter:google/gemini-2.5-pro`, `ollama:llama3.1:8b`).
OpenRouter requests pin routing: `provider: {order: [...], allow_fallbacks: false}` when a backend is configured, and request usage accounting so `cost_usd` is populated.

**loop** - `run(provider, model, system, messages, tools, limits) -> LoopResult{final_text, transcript, stop, counters}`.
Repeats: call model -> if tool calls, dispatch each, append results -> continue.
Stops on: no tool calls (`stop=done`), `max_steps` (`stop=max_steps`), `token_budget` exceeded (`stop=budget`), wall-clock (`stop=timeout`), or provider failure after retries (`stop=error`).
Counters: steps, tool_calls, tool_errors, retries, truncated_bytes.

**tools** - plain functions with a JSON schema each. All paths resolved inside the case checkout; anything escaping it is a tool error. Output truncated at `max_tool_output_bytes` (default 20 KB) with a `[truncated N bytes]` marker.

**roles/reviewer** - builds the system prompt and user message (the diff plus a short instruction), and parses the final answer into findings:
`Finding = {file, line, claim, confidence: 0..1}`. Final answer must be a JSON array in a fenced block. One repair prompt if parsing fails; second failure means zero findings and `parse_failures += 1`.

**datasets** - `Case = {id, dataset, checkout_path, diff, ground_truth: list[{file, start, end}]}`.

- BugsInPy: the diff shown is the reverse of the fixing commit (i.e. the bug-introducing change); the checkout is the buggy commit; ground truth is the fix's touched ranges in buggy-version line numbers. Repos are cloned to `~/.cache/whippletree/bugsinpy/`.
- Seeded: same shape, stored under `datasets/seeded/<case-id>/` with `diff.patch`, `truth.json`, and a small source tree.

**scoring** - pure function `score(findings, ground_truth, line_window=5) -> CaseScore`.
A finding hits a ground-truth range if the file matches and the line falls within `[start - N, end + N]`. Multiple hits on one range = one TP plus `dupes`. Non-hitting findings = FP. Case recall = 1 if any range hit.
Run-level: recall (per case), precision (per finding), F1, $/TP, tokens/TP, tool_errors, parse_failures, errored cases (excluded from precision/recall, reported separately). PR curve over confidence thresholds.

**traces** - one JSONL file per run in `runs/<run-id>.jsonl`. First line is a header: run id, git SHA, model, served_by, settings, dataset + version, limits. Then one line per model call (tokens, cost, latency, stop_reason, tool calls) and one per case result. Write-only; `report` reads it back.

**cli**

- `whippletree run review --dataset {bugsinpy,seeded} --model <provider:model> [--limit N] [--repeat K] [--case ID]`
- `whippletree report <run-id> [<run-id> ...]` - prints a metrics table; side-by-side for multiple runs.

### Data flow

dataset -> Case -> reviewer builds prompt -> loop (provider + tools on checkout) -> final text -> parse findings -> score vs ground truth -> trace. `report` aggregates traces.

## Error handling and limits

| Condition | Handling | Recorded as |
| --- | --- | --- |
| 429 / 5xx | retry, exponential backoff, 3 tries | `retries` |
| Provider still failing | case marked errored | `stop=error`, excluded from P/R |
| Bad tool-call JSON / unknown tool / path escape | error string returned to model as tool result | `tool_errors` |
| Unparseable findings | one repair prompt, then zero findings | `parse_failures` |
| Oversized tool output | truncated with marker | `truncated_bytes` |
| Budget / steps / time exhausted | stop; partial findings still parsed and scored | `stop=budget | max_steps | timeout` |

Defaults: `max_steps=20`, `token_budget=200_000`, `wall_clock=300s`, temperature 0 where supported.
Cost: provider-reported `cost_usd` when present, else `pricing.py` table; the trace records which source was used.

## Known biases (reported, not hidden)

1. FPs may be real bugs BugsInPy doesn't label. v0: hand-audit ~20 FPs per model, report the real-bug share. No LLM judge.
2. Diffs are small and focused, so easier than real PRs. Later: bury the bug among unrelated commits.
3. Contamination: models may have seen these repos. The seeded set is the control.
4. One BugsInPy bug per case; some fixes touch several hunks - all ranges count as the one bug for recall.

## Testing

Test-first throughout.

- **providers:** recorded JSON responses as fixtures; no network.
- **loop:** fake provider returning a scripted sequence; one test per stop reason and per error-handling row.
- **scoring:** table-driven tests (hits, window edges, dupes, FPs, empty).
- **datasets:** one tiny fixture case per loader.
- **reviewer parsing:** valid, fenced, malformed, repaired.
- **live smoke (marked `live`, not in CI):** `whippletree run review --dataset seeded --model ollama:llama3.1:8b --limit 1`.

## Repo hygiene

- Public GitHub repo `MichaelPaulukonis/whippletree` (created after the first working commit), MIT license.
- Secrets only in `.env` (gitignored); `gitleaks` pre-commit hook from the first commit.
- CI: GitHub Actions running `ruff check` and `pytest -m "not live"`.
- `runs/` gitignored; `results/` committed.
- README: purpose, hypotheses, how to run, public-domain whippletree photo, one line on the minimal-dependency choice.
- Task tracking: `bd init` in this repo (Claude-only cleanup steps); umbrella bead `research-8m0` stays in the research repo.

## Out of scope for v0

Code execution / Docker, native Anthropic and Gemini adapters, coder and test-writer roles, SWE-bench, REPL, context compaction, LLM-as-judge, parallel case execution.

## Done when

- `whippletree run review` runs end to end on the seeded set with an Ollama model and on >= 20 BugsInPy cases with at least two OpenRouter models.
- `whippletree report` prints recall, precision, F1, $/TP, tokens/TP, tool_errors, parse_failures for each.
- Unit tests pass in CI; no secrets in the repo history (gitleaks clean).
