# whippletree

Self-built Python harness that benchmarks cross-model code review. A reviewer agent gets a PR-style diff containing one known bug, explores the repo with read-only tools (`read_file`, `list_dir`, `grep`), and submits findings. Whippletree scores them against ground truth and logs every model call to a JSONL trace. Milestone 1 runs on a hand-seeded set and on BugsInPy (real bugs, padded diffs).

## Commands

```bash
uv sync
uv run pytest                    # unit tests
uv run pytest -m live            # needs local Ollama with llama3.1:8b; not run by default
uv run ruff check .

uv run whippletree run baseline --dataset seeded
uv run whippletree run review --dataset seeded --model ollama:llama3.1:8b
uv run whippletree run review --dataset seeded --model openrouter:google/gemini-4-argon --routing google-vertex
uv run whippletree run baseline --dataset bugsinpy --limit 24   # first run clones into ~/.cache/whippletree/bugsinpy/
uv run whippletree run review --dataset bugsinpy --limit 24 --model openrouter:google/gemini-4-argon
uv run whippletree report <run-id> [<run-id> ...]
```

## Architecture

providers (`providers/`, OpenRouter and Ollama via the openai SDK) -> loop (`loop.py`, role-agnostic agent loop) -> roles (`roles/reviewer.py`: prompt, tools, `submit_findings`) -> runner (`runner.py`, per-case records and cost) -> traces (`traces.py`, JSONL) and report (`cli.py`). `scoring.py` is pure: no I/O, re-scores from the trace alone. Shared types are in `case.py`; usage/setup errors raise `WhippletreeError` (`errors.py`) and the CLI prints them as one line and exits 2.

## Where things are

- Spec: `docs/superpowers/specs/2026-11-01-whippletree-design.md`
- Plan: `docs/superpowers/plans/2026-11-02-whippletree-core.md`, `docs/superpowers/plans/2026-11-03-whippletree-bugsinpy.md`
- BugsInPy cache: `~/.cache/whippletree/bugsinpy/`. Delete the dir to rebuild.
  - BugsInPy metadata (shallow, never refreshed on purpose, for reproducibility; delete to refresh), blobless full-history project clones under `repos/`, one detached worktree per case at the buggy commit under `checkouts/`.
  - First run needs network. Warm the cache with one run (e.g. the baseline) before running several models in parallel; concurrent cold-cache runs can clobber each other's clones.
  - Load-time skips go to stderr and the trace header; `report` shows a `skipped at load:` line. On a cold cache, `clone-failed` / `git-error` skips can mean the network was down; `commit-missing` means the buggy commit isn't reachable in the clone.
  - Default projects (small repos): PySnooper, cookiecutter, httpie, sanic, tqdm, thefuck. `--case bugsinpy/<project>/<n>` works for any BugsInPy project.
- Seeded cases: `datasets/seeded/`; raw traces: `runs/` (gitignored); curated results: `results/`

## Conventions

- Tests first; fakes live in `tests/fakes.py`.
- One failing case must never sink a run: harness failures are recorded as errored, not as model misses.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
