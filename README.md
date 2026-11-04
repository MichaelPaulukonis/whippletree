# whippletree

Whippletree is a self-built coding-agent harness. Milestone 1 benchmarks code review across models: a reviewer agent reads a PR-style diff containing one known bug, uses read-only tools on the repository, and submits findings. Whippletree scores them against ground truth and logs every model call.

**Status:** the harness runs end to end on a small hand-seeded set and on BugsInPy cases. No benchmark results yet.

![Twenty-six horse combined harvester at work, Washington, 1905](docs/img/twenty-six-horse-combine-1905.jpg)

*Twenty-six horse combined harvester at work, reaping, threshing and sacking, Wash., U.S.A. Stereograph, H. C. White Co., 1905. [New York Public Library](https://digitalcollections.nypl.org/search/index?keywords=G92F080_041F), Robert N. Dennis collection of stereoscopic views. Public domain in the US.*

A whippletree is the crossbar that balances the pull between several horses hitched to one load; stack them and twenty-six horses pull one harvester. Whippletrees also did addition in mechanical computers and hold Alexander Calder's mobiles in balance. Here the horses are models.

## Hypotheses

- **H1:** a cheap model plus a verifier gets >= 80% of a frontier model's recall at <= 20% of the cost.
- **H2:** cross-model review catches bugs that self-review misses.
- **H3:** native provider adapters cut cost vs. OpenRouter (prompt caching).

## Prerequisites

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- For local runs: [Ollama](https://ollama.com) running, then `ollama pull llama3.1:8b`.
- For hosted models: an [OpenRouter](https://openrouter.ai) API key in `.env`.
- Run from a source checkout: the seeded cases live in the repo's `datasets/` directory, not in the installed package.

## Run it

```bash
uv sync
git config core.hooksPath .beads/hooks   # beads + gitleaks pre-commit hook
cp .env.example .env                     # add OPENROUTER_API_KEY for OpenRouter models

uv run whippletree run baseline --dataset seeded
uv run whippletree run review --dataset seeded --model ollama:llama3.1:8b
uv run whippletree run review --dataset seeded --model openrouter:google/gemini-2.5-pro --routing google-vertex
uv run whippletree run baseline --dataset bugsinpy --limit 24   # first run clones into ~/.cache/whippletree/bugsinpy/
uv run whippletree run review --dataset bugsinpy --limit 24 --model openrouter:google/gemini-2.5-pro
uv run whippletree report <run-id> [<run-id> ...]
```

`--routing` pins the OpenRouter backend by provider slug (OpenRouter's `provider.order` takes slugs such as `google-vertex`, not display names; copy the slug from the model's page on openrouter.ai). Fallbacks are disabled, so a request fails rather than being served by a different backend.

The BugsInPy cache lives in `~/.cache/whippletree/bugsinpy/`; delete it to rebuild.

- Layout: BugsInPy metadata (shallow, never refreshed on purpose, for reproducibility; delete to refresh), blobless full-history project clones under `repos/`, one detached worktree per case at the buggy commit under `checkouts/`.
- The first run needs network. Warm the cache with one run (e.g. the baseline) before running several models in parallel; concurrent cold-cache runs can clobber each other's clones.
- Load-time skips are printed to stderr and recorded in the trace header; `report` shows a `skipped at load:` line. On a cold cache, `commit-missing` skips can mean the network was down, not that the dataset is wrong.
- Default projects (small repos): PySnooper, cookiecutter, httpie, sanic, tqdm, thefuck. `--case bugsinpy/<project>/<n>` works for any BugsInPy project.

Traces go to `runs/<run-id>.jsonl` (gitignored). Curated results go in `results/`.

### Sample report

The random baseline (3 guesses per case, seed 0) on the 2-case seeded set, as printed by `whippletree report`:

```
run 20261102T204724Z-f61c13  model=baseline:random  dataset=seeded  served_by=-
  cases 2 scored + 0 errored  recall 0.50  precision 0.17  F1 0.25
  cost $0.0000  $/found $0.0000  tokens/found 0
  cost sources: none 2
  tool_errors 0  parse_failures 0
  stops: done 2
  recall by kind: deletion 0.00, modification 1.00
  PR curve: >=0.0 P0.17 R0.50 | >=0.5 P0.17 R0.50 | >=0.7 P- R0.00 | >=0.9 P- R0.00
```

A model has to beat this floor. Runs made from a tree with uncommitted changes get an extra `WARNING: run made from uncommitted changes (git_dirty)` line.

## Tests

```bash
uv run pytest            # unit tests, no network
uv run pytest -m live    # smoke test against a local Ollama (llama3.1:8b)
uv run ruff check .
```

## Design choices

- One runtime dependency (`openai`, pinned in `uv.lock`). No LiteLLM, no agent frameworks: fewer supply-chain risks, and the provider differences stay visible.
- OpenRouter routing is pinned per run so a model id isn't silently served by different backends.
- Harness-caused failures (timeouts, provider errors) are counted as errored, not as model misses, and every stop reason is reported.
- Spec: `docs/superpowers/specs/2026-11-01-whippletree-design.md`.

## License

MIT
