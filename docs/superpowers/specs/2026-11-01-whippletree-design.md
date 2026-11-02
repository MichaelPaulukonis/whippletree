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
| later | SZZ realism-check subset; context management / token budgets (C); safety and permissions (D); optional REPL | separate |

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
      env.py             ToolEnv (1a: checkout_path; 1b: + sandbox handle)
      fs.py              read_file, list_dir, grep (built per case from ToolEnv)
    roles/
      reviewer.py        system prompt, submit_findings terminal tool + validation
    baseline.py          dumb reviewer (random changed lines in the diff) - scoring sanity check
    case.py              Range, Padding, Case, Finding (shared domain types)
    errors.py            WhippletreeError (usage/setup errors; the CLI prints one line, exits 2)
    datasets/
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
OpenRouter requests pin routing: `provider: {order: [...], allow_fallbacks: false}` when a backend is configured, and request usage accounting so `cost_usd` is populated. Assistant-message `reasoning` / `reasoning_details` are echoed back on later turns (Gemini thought signatures and Anthropic thinking blocks require it in tool loops).

**loop** - `run(provider, model, system, messages, tools, limits) -> LoopResult{result, transcript, stop, counters}`.
Repeats: call model -> if tool calls, dispatch each, append results -> continue.
A tool may be marked **terminal**: when it returns successfully, the loop stops with `stop=done` and its return value becomes `LoopResult.result`. A terminal tool that fails validation returns an ordinary error string, so the model gets another turn inside the same step and token limits.
Stops on: terminal tool succeeded (`stop=done`), a turn with no tool calls after one nudge (`stop=no_submit`), `max_steps` (`stop=max_steps`), `token_budget` exceeded (`stop=budget`), wall-clock (`stop=timeout`), or provider failure after retries (`stop=error`).
Counters: steps, tool_calls, tool_errors, retries, truncated_bytes, nudges, warnings, truncated_outputs.
The model is told the step limit up front and gets one last-chance warning ("call `submit_findings` now") before its final allowed turn or once token use reaches 80% of the budget. Wall clock excludes retry backoff and is also checked after each call; a submission in the response that crossed the limit is still kept. Responses cut off by the model's max output length (`stop_reason=length`) are counted in `truncated_outputs`, and a resulting bad-JSON tool error says the output was cut off.
The loop is flat and single-agent. It knows nothing about roles, datasets, or where tools execute.

**tools** - plain functions with a JSON schema each, built per case from a `ToolEnv`. In 1a, `ToolEnv` holds `checkout_path`; in 1b it also holds the Docker sandbox handle, so the loop never changes between local and container execution. All paths resolve inside the checkout; anything escaping it is a tool error. Output truncated at `max_tool_output_bytes` (default 20 KB) with a `[truncated N bytes]` marker.

**roles/reviewer** - builds the system prompt and user message: the case's PR-style diff plus a short instruction to review it for bugs, using the tools to read surrounding code as needed. Provides the terminal tool `submit_findings(findings: list[Finding])`, where `Finding = {file, line, claim, confidence: 0..1}`. Validation checks the schema, types, and confidence range; it does not check that the file or line exists (that would leak hints). Validation failures count as `parse_failures` as well as `tool_errors`. The system prompt states the step limit (filled from the `Limits` in use). If the loop ends with `stop=no_submit`, the case scores zero findings.

**datasets** - `Case = {id, dataset, checkout_path, diff, padding: {base, commits, changed_lines}, ground_truth: list[{file, start, end}]}`.

- BugsInPy, **padded diffs**: the bare reversed fix diff is never shown on its own, because the whole diff would be the bug. Instead each case is one real, coherent PR-sized diff that ends at the buggy commit `B`:
  1. Walk back first-parent from `B` to pick a base `B~K`, choosing the smallest K whose `B~K..B` diff brings the total to >= 80 changed lines. Cap at 250; skip a commit that alone exceeds the cap.
  2. Apply the fix patch (`B -> F`) onto `B~K` to make a synthetic base `X`. If the fix doesn't apply cleanly there, try a smaller K; if only K=0 works, skip the case.
  3. `Case.diff = git diff X B`: K commits of real work plus the bug's introduction, with one (or a few) bug hunks among several innocent ones.
  - The checkout stays at `B`, so the diff's post-image matches what the tools read. Ground truth is the fix's touched ranges in `B`'s line numbers.
  - A fix hunk that only adds lines (e.g. a missing guard clause) has no lines in `B`, so it becomes a zero-width range at the insertion point (`start = end =` the line before the insertion).
  - Skipped cases are counted and reported, with the reason. The `padding` record (base, commits, changed lines) goes into the trace so every diff can be rebuilt.
  - Repos are cloned to `~/.cache/whippletree/bugsinpy/`.
- Seeded: same shape, stored under `datasets/seeded/<case-id>/` as two small source trees, `before/` and `after/` (one planted bug in `after/`), plus `truth.json`. The diff is generated from the two trees (`git diff --no-index`, with tree names stripped from header paths only), not hand-written; the checkout is `after/`.

**scoring** - pure function `score(findings, ground_truth, line_window=5) -> CaseScore`.
A finding hits a ground-truth range if the file matches and the line falls within `[start - N, end + N]`. With padded diffs of 80-250 changed lines across several hunks, an 11-line window is a real localization test. Multiple hits on one range = one TP plus `dupes`. Non-hitting findings = FP. Case recall = 1 if any range hit.
Run-level: recall (per case), precision (per finding), F1, $/TP, tokens/TP, tool_errors, parse_failures, errored cases (excluded from precision/recall, reported separately; still counted in cost and tokens). A case is errored when it stopped with `stop=error` or `stop=timeout`: those are harness or provider outcomes, not model misses. $/TP and tokens/TP divide by found cases (a case counts once however many ranges were hit). A metric with no data (no findings, or no non-errored cases) is reported as undefined, not 0. PR curve over confidence thresholds.
No automated matching of `claim` text against commit messages (too brittle; fix messages are often just "Fix #123").

**baseline** - `whippletree run baseline --dataset ... --strategy random` emits K findings at random changed lines of the case diff (post-image line numbers), skipping the loop and providers. Its scores set the floor every model must beat and confirm the scoring can't be gamed by guessing lines.

**traces** - one JSONL file per run in `runs/<run-id>.jsonl`, created exclusively (an existing path is an error, never overwritten). First line is a header: run id, mode, model, dataset, `git_sha` and `git_dirty` (computed in the whippletree checkout, not the process cwd), `version`, `argv`, `case_filter`, `limit`, `dataset_hash` (sha256 over the loaded, filtered cases sorted by id: id, diff, ground truth), `window` and `thresholds` (scoring defaults), settings, limits, routing and repeat (review runs), `system_prompt_sha` (sha256 of the system prompt actually sent, not of the tool schemas or user message; review runs), and k and seed (baseline runs). served_by is recorded per call, not in the header; `report` lists the distinct values and warns when more than one backend served a run. Then one line per model call (tokens, cost, latency, stop_reason, tool calls) and one per case result; review case events include the full loop transcript so failures can be diagnosed from the trace. A run that finishes writes a final `end` event with the case count; `report` prints `WARNING: incomplete run (no end event)` when it is missing. `report` re-scores from the trace alone.

**cli**

- `whippletree run review --dataset {bugsinpy,seeded} --model <provider:model> [--limit N] [--repeat K] [--case ID]`
- `whippletree run baseline --dataset {bugsinpy,seeded} --strategy random [--limit N]`
- `whippletree report <run-id> [<run-id> ...]` - prints one metrics block per run (a side-by-side table is later work). Errors (unknown run id, bad model spec, missing API key, no matching cases) print a one-line `whippletree: <message>` to stderr and exit 2.

### Data flow

dataset -> Case -> ToolEnv + tools -> reviewer builds prompt -> loop (provider + tools) -> `submit_findings` result -> score vs ground truth -> trace. `report` aggregates traces.

### Phase 2 orchestration (noted now, built later)

Phase 2 (coder -> test-writer -> reviewer) is a sequential Python pipeline that calls `loop.run()` once per role and passes artifacts (diffs, test files, findings) between calls. No nested subagents-as-tools. That keeps token attribution, cost, and trace files flat across phases.

## Error handling and limits

| Condition | Handling | Recorded as |
| --- | --- | --- |
| 429 / 5xx | retry, exponential backoff, 3 retries (4 attempts) | `retries` |
| Provider still failing | case marked errored | `stop=error`, excluded from P/R |
| Bad tool-call JSON / unknown tool / path escape | error string returned to model as tool result | `tool_errors` |
| Invalid `submit_findings` call | error returned as tool result; model retries within limits | `parse_failures`, `tool_errors` |
| Turn with no tool calls, no submission | one nudge ("call `submit_findings`"), then stop with zero findings | `nudges`, `stop=no_submit` |
| Oversized tool output | truncated with marker | `truncated_bytes` |
| Model output cut off at max output length | counted; a bad-JSON tool error says the output was cut off | `truncated_outputs` |
| Last turn coming up, or 80% of token budget used | one last-chance warning to submit now | `warnings` |
| Budget / steps exhausted | stop; zero findings (nothing was submitted) | `stop=budget | max_steps` |
| Wall clock exceeded (retry backoff excluded) | stop; case marked errored unless the last response submitted | `stop=timeout`, excluded from P/R |

Defaults: `max_steps=20`, `token_budget=200_000`, `wall_clock=300s`, temperature 0 where supported.
Cost: provider-reported `cost_usd` when present, else `pricing.py` table; the trace records which source was used.

## Known biases (reported, not hidden)

1. Line matching can't judge the diagnosis. v0 hand-audits ~20 FPs per model (report the share that are real, unlabeled bugs) and ~20 TPs per model (report the "right line, wrong diagnosis" rate). No LLM judge.
2. Reversal artifact: the bug hunk is a fix played backwards, so it often reads as "a check was deleted", while the padding hunks read as ordinary forward work. A model may learn to spot deletions rather than bugs. Report recall split by bug hunk type (pure deletion vs. modification); the seeded set, where bugs are written forward, is the comparison.
3. Padding is synthetic: real bug-introducing PRs mix the bug with *related* work, while padding commits may be unrelated. Later realism check: an SZZ subset (blame the fix's lines back to the commit that introduced them) on the ~60% of cases where SZZ resolves cleanly.
4. Contamination: models may have seen these repos. The seeded set is the control.
5. One BugsInPy bug per case; some fixes touch several hunks - all ranges count as the one bug for recall.

## Testing

Test-first throughout.

- **providers:** recorded JSON responses as fixtures; no network.
- **loop:** fake provider returning a scripted sequence; one test per stop reason and per error-handling row, including terminal-tool success, terminal-tool validation failure then retry, and nudge then `no_submit`.
- **scoring:** table-driven tests (hits, window edges, zero-width insertion ranges, dupes, FPs, empty).
- **datasets:** one tiny fixture case per loader, including an add-only fix hunk. Padding builder against a small fixture git repo: picks K by line budget, skips oversized commits, falls back when the fix won't apply, skips when only K=0 works, and the diff's post-image equals `B`.
- **reviewer:** `submit_findings` validation (valid, missing keys, wrong types, confidence out of range).
- **baseline:** deterministic under a fixed seed.
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
- The random baseline has been run on the same cases, and every model is reported next to it.
- Unit tests pass in CI; no secrets in the repo history (gitleaks clean).
