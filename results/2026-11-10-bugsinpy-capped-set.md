# BugsInPy capped case set (replaces the M1 24-case set)

M1's `--limit 24` set took projects in order, so thefuck supplied 13 of 24 cases (see `2026-11-05-bugsinpy-m1.md`, Caveats). The five other original projects only yield 11 buildable cases between them, so a cap alone would have shrunk the set. Change: `--per-project` (default 4) plus six more default projects (black, fastapi, luigi, scrapy, tornado, youtube-dl). Run with no `--limit`.

- `dataset_hash daec940358f0...` (full: `daec940358f095c1495116eb7a1d6f98141aed11105f195fb9503bea9568583f`), `per_project=4`
- 39 cases from 12 projects: PySnooper 1, cookiecutter 1, httpie 2, tqdm 3, and 4 each from sanic, thefuck, black, fastapi, luigi, scrapy, tornado, youtube-dl. No project over ~10%.
- 66 considered, 27 skipped at load: padding-under-min-lines 11, fix-does-not-apply 7, bug-commit-over-cap 6, patch-touches-tests 2, padding-out-of-bounds 1.

M1 numbers are not comparable to runs on this set. Every model needs re-running.

## Baseline

| Run id | Model | git sha | Recall | Precision | F1 |
| --- | --- | --- | --- | --- | --- |
| `20261110T211825Z-1e8ec3` | `baseline:random` (k=3, seed 0) | `03a18b5` | 0.10 | 0.08 | 0.09 |

Random recall is up from 0.04 on M1 (4 hits of 39 vs 1 of 24); not investigated, n is tiny.
