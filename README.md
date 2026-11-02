# whippletree

A whippletree is the crossbar that balances the pull between several horses hitched to one load. Here the horses are models.

Whippletree is a self-built coding-agent harness. Milestone 1 benchmarks code review across models: a reviewer agent reads a PR-style diff containing one known bug, uses read-only tools on the repository, and submits findings. Whippletree scores them against ground truth and logs every model call.

**Status:** the harness runs end to end on a small hand-seeded set. No benchmark results yet; BugsInPy cases are next.

## Hypotheses

- **H1:** a cheap model plus a verifier gets >= 80% of a frontier model's recall at <= 20% of the cost.
- **H2:** cross-model review catches bugs that self-review misses.
- **H3:** native provider adapters cut cost vs. OpenRouter (prompt caching).

## Run it

```bash
uv sync
git config core.hooksPath .beads/hooks   # beads + gitleaks pre-commit hook
cp .env.example .env                     # add OPENROUTER_API_KEY for OpenRouter models

uv run whippletree run baseline --dataset seeded
uv run whippletree run review --dataset seeded --model ollama:llama3.1:8b
uv run whippletree run review --dataset seeded --model openrouter:google/gemini-2.5-pro --routing Google
uv run whippletree report <run-id> [<run-id> ...]
```

Traces go to `runs/<run-id>.jsonl` (gitignored). Curated results go in `results/`.

## Design choices

- One runtime dependency (`openai`, pinned in `uv.lock`). No LiteLLM, no agent frameworks: fewer supply-chain risks, and the provider differences stay visible.
- OpenRouter routing is pinned per run so a model id isn't silently served by different backends.
- Harness-caused failures (timeouts, provider errors) are counted as errored, not as model misses, and every stop reason is reported.
- Spec: `docs/superpowers/specs/2026-11-01-whippletree-design.md`.

## License

MIT
