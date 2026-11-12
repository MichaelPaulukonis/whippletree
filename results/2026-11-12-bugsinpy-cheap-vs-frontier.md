# Cheap vs frontier reviewers on the capped BugsInPy set

Runs 2026-11-12 (UTC), bead whippletree-v7l. Question (trimmed H1): how close does a cheap reviewer get to frontier recall with no verifier? 39 cases, one bug each, `dataset_hash daec940358f0...` on every run (same set as `2026-11-10-bugsinpy-capped-set.md`). Clean tree at `26278b8` for all five model runs. One pass each (`--repeat 1`), so no variance estimate: treat differences of a few cases as noise.

| Run id | Model | Routing (served by) |
| --- | --- | --- |
| `20261110T211825Z-1e8ec3` | `baseline:random` (k=3, seed 0) | - |
| `20261112T201306Z-7fa6df` | `openrouter:anthropic/claude-opus-5.5` | unpinned (Claude Platform on AWS) |
| `20261112T201306Z-5b74d0` | `openrouter:google/gemini-4-argon` | `google-vertex` (Google) |
| `20261112T201306Z-8dd67d` | `openrouter:mistralai/mistral-large-4-0` | `mistral` |
| `20261112T201306Z-ebcfc3` | `openrouter:moonshotai/kimi-k2.7-code` | `moonshotai` (pinned: other hosts serve int4/fp8 quants) |
| `20261112T201306Z-af5e9c` | `openrouter:mistralai/devstral-2512` | `mistral` |

Limits for all runs: `max_steps 20`, `token_budget 200000` (input+output summed over a case), `wall_clock_s 300`.

## Summary

| | Random | Opus 5.5 | Gemini 4 Argon | Mistral Large 4 | Kimi K2.7 Code | Devstral 2512 |
| --- | --- | --- | --- | --- | --- | --- |
| Recall | 0.10 (4/39) | **0.95** (37/39) | 0.82 (32/39) | 0.74 (29/39) | 0.64 (25/39) | 0.54 (21/39) |
| Precision | 0.08 | 0.57 | 0.59 | 0.53 | 0.57 | **0.65** |
| F1 | 0.09 | **0.72** | 0.69 | 0.62 | 0.61 | 0.59 |
| Cost (39 cases) | $0 | $5.86 | $3.29 | $1.87 | $2.80 | **$0.62** |
| Cost per PR | - | $0.150 | $0.084 | $0.048 | $0.072 | **$0.016** |
| $/bug found | - | $0.16 | $0.10 | $0.06 | $0.11 | **$0.03** |
| Tokens/bug found | - | **35k** | 135k | 213k | 234k | 276k |
| Stops | done 39 | done 39 | done 39 | done 37, budget 2 | done 32, budget 7 | done 24, max_steps 13, budget 2 |
| Tool errors | - | 2 | 0 | 38 | 1 | 10 |

PR curve (precision / recall at confidence threshold):

| Threshold | Opus 5.5 | Gemini 4 Argon | Mistral Large 4 | Kimi K2.7 Code | Devstral 2512 |
| --- | --- | --- | --- | --- | --- |
| >= 0.0 | 0.57 / 0.95 | 0.59 / 0.82 | 0.53 / 0.74 | 0.57 / 0.64 | 0.65 / 0.54 |
| >= 0.5 | 0.69 / 0.87 | 0.59 / 0.82 | 0.54 / 0.72 | 0.57 / 0.64 | 0.65 / 0.54 |
| >= 0.7 | 0.77 / 0.51 | 0.59 / 0.82 | 0.62 / 0.67 | 0.60 / 0.64 | 0.65 / 0.54 |
| >= 0.9 | 1.00 / 0.13 | 0.59 / 0.77 | 0.55 / 0.41 | 0.63 / 0.51 | 0.65 / 0.54 |

## Findings

- **Every model beats random by a wide margin.** Random finds 4 of 39.
- **No cheap model gets close to Opus on recall.** Best cheap model, Mistral Large 4, finds 29 vs Opus's 37 (78% of Opus recall) at 32% of Opus's cost per PR. Gemini sits between.
- **Cheap per token is not cheap per bug.** Cheap models explore far longer: Opus reads a file or two and submits (35k tokens per bug found); the others use 135k-276k. Kimi ends up at Gemini's $/bug with 7 fewer finds.
- **Devstral is the cost floor and the recall floor.** $0.016 per PR, but it misses nearly half the bugs; 13 of its cases ran out of steps without submitting.
- **Only Opus has a usable confidence knob.** Its precision climbs from 0.57 to 1.00 with the threshold. Gemini and Devstral rate everything the same, so their curves are flat; Mistral Large and Kimi move a little.
- **Mistral Large has 38 tool errors** (about one per case); not investigated yet (whippletree-ihg hand audit).

## Caveats

- **Token cap hits the cheap models, not the frontier ones.** The 200k budget counts tokens, not dollars, and every call resends the whole conversation, so models that explore longer hit it while still costing pennies. 11 cases ended on `budget` (Mistral Large 2, Kimi 7, Devstral 2) and count as misses here. Opus never came near it (max 154k); Gemini went over once but on the call that submitted. See the re-run section below.
- **Opus cost more than M1.** $0.15 per PR here vs ~$0.10 on M1's 24 cases; the new projects (black, scrapy, tornado, ...) are bigger.
- **Two earlier attempts the same day were lost to OpenRouter 402s** (workspace daily budget, then the harness key's weekly limit): runs `20261112T170016Z-*` and `20261112T201002Z-*`. Discarded, not used anywhere here. Filed whippletree-8fa (stop a run on 402).

## Token-budget re-run (separate, not merged above)

Question: were the 11 `budget` stops real misses, or did the cap cut off reviews that were going somewhere? Each was re-run once with `--token-budget 400000`; everything else the same (model, routing, `max_steps 20`, system prompt sha). Traces are kept apart in `runs/budget-400k/`, one run per case.

Differences from the main runs:

- **Token budget 400k** instead of 200k (recorded in each trace header's `limits`).
- **`git_dirty: true`**: the only uncommitted change was the new `--token-budget` flag (diff saved as `runs/budget-400k/git-dirty.diff`). Case building and scoring are untouched.
- **`dataset_hash` differs per run** because each run is a single-case set. Same case ids, same cache, same commit, so the cases are the same.
- **Fresh samples.** Raising the cap cannot change a case that finished under 200k (the 80%-of-budget warning is not wired into the reviewer, so nothing else moves with the cap). But a re-run is a new draw, so a hit here is "found with more room on another try", not "would have been found on the first try".

| Model | Case | Run id | Stop | Tokens | Cost | Found |
| --- | --- | --- | --- | --- | --- | --- |
| Mistral Large 4 | `black/2` | `20261112T213025Z-1fe05c` | done | 340k | $0.09 | no (1 FP) |
| Mistral Large 4 | `luigi/7` | `20261112T213432Z-359302` | done | 436k | $0.11 | no (submitted nothing) |
| Kimi K2.7 Code | `sanic/1` | `20261112T213025Z-7efd93` | max_steps | 369k | $0.11 | no |
| Kimi K2.7 Code | `thefuck/2` | `20261112T213158Z-60bd10` | done | 158k | $0.10 | **yes** |
| Kimi K2.7 Code | `black/2` | `20261112T213524Z-809873` | done | 244k | $0.11 | no (submitted nothing) |
| Kimi K2.7 Code | `luigi/5` | `20261112T213808Z-86642c` | done | 273k | $0.12 | no (submitted nothing) |
| Kimi K2.7 Code | `scrapy/3` | `20261112T214114Z-c7382b` | done | 145k | $0.06 | no (submitted nothing) |
| Kimi K2.7 Code | `tornado/8` | `20261112T214238Z-8ac0c1` | max_steps | 238k | $0.08 | no |
| Kimi K2.7 Code | `youtube-dl/2` | `20261112T214437Z-8727fe` | done | 354k | $0.12 | **yes** |
| Devstral 2512 | `black/3` | `20261112T213025Z-debadb` | max_steps | 257k | $0.02 | no |
| Devstral 2512 | `tornado/9` | `20261112T213051Z-ec49a0` | done | 288k | $0.02 | **yes** |

3 of 11 found, $0.93 total. Three more ran into `max_steps` instead, and five submitted with no finding on the bug (four submitted nothing at all). Two of the Kimi cases (`thefuck/2`, `scrapy/3`) finished under 200k this time, so those are sampling differences, not the cap.

If the re-run results replaced the budget stops (for illustration only; mixes caps and samples): Mistral Large stays 0.74, Kimi 0.64 -> 0.69, Devstral 0.54 -> 0.56. **Ranking unchanged; the cap is not what separates the cheap models from Opus.** Mostly they run long because they don't converge, and more room mostly buys more wandering.
