# Spec Review: Whippletree (Milestone 1, v0)

Review of `docs/superpowers/specs/2026-11-01-whippletree-design.md`.

## Overall Assessment

The stack, scope discipline, and core harness boundaries (`providers/`, `loop.py`, `tools/`, `traces.py`) are strong. Using Python 3.13, `uv`, `dataclasses`, `argparse`, and the raw `openai` SDK without framework wrappers fits the goal of learning harness internals and exposing failure modes. Pinning OpenRouter provider routing (`allow_fallbacks: false`) and logging `served_by` is a great call that avoids the most common benchmarking trap on OpenRouter.

However, there are **two experimental validity issues** (how PR diffs are constructed and scored) and **two small architectural adjustments** (how findings are returned and how tools bind to the workspace) that should be changed before building v0.

---

## Required Changes

### 1. Case Input: Pad the Reversed Fix Diff with Adjacent Commits (Do Not Defer to "Later")

**Current spec (lines 92, 127):**
> BugsInPy: the diff shown is the reverse of the fixing commit (i.e. the bug-introducing change); the checkout is the buggy commit; ground truth is the fix's touched ranges in buggy-version line numbers.
> Known biases: 2. Diffs are small and focused, so easier than real PRs. Later: bury the bug among unrelated commits.

**Why this breaks v0 if deferred:**
A fixing commit (`B -> F`) only touches the exact 3-15 lines of the bug. Reversing that (`F -> B`) produces a tiny diff where 100% of the diff is the bug (and often looks like someone solely deleting a guard clause). Handing a reviewer a 5-line diff and asking "where is the bug in this diff?" makes localization trivial and renders the v0 baseline numbers meaningless.

**Why alternatives like `git blame` /whole-file don't fit as well:**
- **Whole-file review** changes the task from PR diff review to static codebase auditing, which doesn't match the primary goal ("choose a personal code-review policy... costs $Y per PR").
- **Finding the real bug-introducing commit via `git blame` / SZZ** only works cleanly on ~60% of a dataset like BugsInPy (the rest span multiple commits across months, are bugs of omission with no blame target, or trace back to massive initial commits).

**Change to:**
Move "bury the bug among unrelated commits" from "Later" into **v0 dataset construction**:
- Combine the reversed fix diff (`F -> B`) with the diffs of `K` surrounding commits (e.g., `B~3..B`) so every `Case.diff` is a realistic ~80-250 line multi-hunk PR diff across several functions/files, with only one hunk containing the actual bug.
- Keep the checkout at the buggy commit `B` and ground truth as the fix's touched line ranges in `B`.

### 2. Scoring: Padded Diffs Make Line-Proximity Valid (+ Add TP Spot-Check)

**Current spec (lines 95-96):**
> A finding hits a ground-truth range if the file matches and the line falls within `[start - N, end + N]`.

**Why this was broken without Change #1:**
Under a 5-15 line isolated fix diff, a `+/- 5` line window (`11+` lines) covered almost the entire diff. A dummy script outputting `{file: diff_file, line: first_diff_line, claim: "nit"}` without calling an LLM would score ~100% recall and precision.

**With Change #1 (padded ~150-line diffs across multiple hunks/files):**
- **Keep pure line-range scoring (`[start - 5, end + 5]`) for automated runs** rather than trying to automatically match `claim` against git commit messages (real-world commit messages are often terse like `"Fix #123"` or describe the fix mechanism rather than the symptom, making automated claim-to-commit matching error-prone).
- **Extend the manual audit (line 126) to True Positives as well as False Positives:** In addition to hand-auditing ~20 FPs per model, verify that line-matched TPs actually diagnosed the right defect in their `claim` field, and report the "right line, wrong diagnosis" rate if non-zero.

### 3. Output Parsing & Repair: Use a `submit_findings` Tool Instead of Fenced Markdown JSON

**Current spec (lines 88, 117):**
> Final answer must be a JSON array in a fenced block. One repair prompt if parsing fails; second failure means zero findings and `parse_failures += 1`.

**Why this is clunky:**
`loop.run()` stops when the model returns a turn with no tool calls, returning `LoopResult` to `reviewer.py`. If `reviewer.py` then parses `final_text` and has to issue a repair prompt on failure, `reviewer.py` either has to call the provider outside `loop.run()` (bypassing step/token/cost accounting in `loop.py`) or `loop.py` needs special-case role validation hooks.

**Change to:**
Give the reviewer a terminal tool: `submit_findings(findings: list[Finding])`.
- When the model calls `submit_findings`, the tool validates the schema (`file`, `line`, `claim`, `confidence` in `0..1`).
- If validation fails (malformed JSON, missing keys, out-of-range confidence), it returns a normal `tool_error` string into the loop transcript and increments `tool_errors` (or `parse_failures`), letting `loop.py` naturally give the model another turn to fix its call within the existing `max_steps` and `token_budget`.
- If validation succeeds, `loop.py` stops with `stop=done` and returns the structured findings directly.
- If the model stops calling tools *without* calling `submit_findings`, `loop.py` can either issue one nudge ("Call `submit_findings` to complete your review") or record a `parse_failure`.

### 4. Future-Proofing for Phase 1b and Phase 2: Explicit `ToolEnv` and Sequential Pipeline

Two lightweight conventions to note in the spec now so Phase 1b (Docker) and Phase 2 (multi-agent) don't force a rewrite of `loop.py`:

1. **Bind tools to an explicit `ToolEnv` / workspace context:**
   In 1a, `tools/fs.py` needs to know the current case's `checkout_path` to resolve paths and prevent escapes. Rather than passing paths via globals, define a small `ToolEnv` (in 1a: holds `checkout_path: Path`; in 1b: also holds the Docker sandbox handle). `tools` are constructed per-case from `ToolEnv`, so `loop.py` stays completely agnostic to local filesystem vs. Docker container.
2. **Document Phase 2 orchestration as a sequential Python pipeline (Pattern A):**
   `loop.py` is designed as a flat, single-agent turn loop. Note explicitly that Phase 2 (`coder -> test-writer -> reviewer`) will be orchestrated by Python calling `loop.run()` sequentially for each role (passing artifacts like diffs and findings between calls), rather than nested subagents-as-tools. That keeps token attribution, cost tracking, and trace files flat and predictable across phases.
