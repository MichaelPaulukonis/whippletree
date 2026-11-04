# Whippletree BugsInPy Loader (M1 v0, Plan 2 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Plan format (thin):** tests are given in full; implementation is given as signatures, docstrings, and gotchas. Write the code test-first to make the given tests pass. Don't add behavior the tests and notes don't ask for.

**Goal:** `--dataset bugsinpy` works: each BugsInPy bug becomes a padded, PR-sized diff ending at the buggy commit, with ground truth in the buggy commit's line numbers, and the M1 "Done when" runs (>= 20 cases x 2 OpenRouter models + random baseline) are done and summarized.

**Architecture:** One new module, `src/whippletree/datasets/bugsinpy.py`. Pure patch parsing (ranges, test-file detection) sits on a small git-plumbing layer: walk first-parent history from `B` to pick a base `B~K`, apply the fix onto it in a throwaway index (`GIT_INDEX_FILE` + `read-tree` + `apply --cached` + `write-tree`, so no checkout is touched), then `git diff X B`. The loader clones the BugsInPy metadata repo and each project repo (blobless) into `~/.cache/whippletree/bugsinpy/`, makes one detached worktree per case at `B`, and returns `(cases, skipped)`. The CLI records skips in the trace header and `report` prints them. Runner, scoring, traces, and baseline are unchanged: `Case.padding` already goes into every `case` trace event.

**Tech Stack:** Python 3.13 stdlib (`subprocess`, `tempfile`, `re`, `shutil`), git CLI, pytest with real throwaway git repos in `tmp_path` (no network in unit tests).

**Spec:** `docs/superpowers/specs/2026-11-01-whippletree-design.md` - datasets (lines 95-104), testing (line 163), done-when (lines 183-186).

---

## Decisions (spec gaps, resolved here)

1. **"Skip a commit that alone exceeds the cap"** - a first-parent walk can't skip a commit in the middle. Read as: the walk stops before the first K that would push `B~K..B` over `max_lines` (250). If `B`'s own commit is already over the cap, skip (`bug-commit-over-cap`).
2. **One base, no fallback (deviates from spec step 2).** The walk picks the smallest K whose `B~K..B` reaches `min_lines` (80). Every smaller K is under `min_lines` by construction, so with strict size bounds a "try smaller K" fallback could almost never succeed. If the fix doesn't apply at the chosen base: skip (`fix-does-not-apply`). Lower yield, much simpler.
3. **Strict size bounds.** Walk can't reach `min_lines` (short history, cap, or `MAX_WALK` commits): skip (`padding-under-min-lines`). Final `X..B` diff outside `[min_lines, max_lines]`: skip (`padding-out-of-bounds`). `Padding.changed_lines` is the final `X..B` size.
4. **Fix patches touching test paths are skipped** (`patch-touches-tests`), about 10 of 502 bugs. Reverting a test file into the diff would plant a "bug" in test code.
5. **Project subset** - `DEFAULT_PROJECTS = ("PySnooper", "cookiecutter", "httpie", "sanic", "tqdm", "thefuck")`, 58 bugs from small repos. `load_bugsinpy` takes `limit` (stop once N cases build) and `case_id` (`bugsinpy/<proj>/<n>`, any project in BugsInPy, builds only that one).
6. **Ground truth is one Range per contiguous change run** (flush on context lines). A run with `-` lines is `modification` spanning the removed lines; a pure `+` run is `deletion`, zero-width at the line before the insertion, matching `Range`'s docstring.
7. **Every other failure is a skip, never a crash:** no ranges (`no-ground-truth`), commit not in repo (`commit-missing`), patch doesn't apply to `B` itself (`patch-does-not-apply-to-buggy`, protects line numbers), a range has no changed line in the final diff (`bug-not-in-diff`), root commit (`no-history`), clone failure (`clone-failed`, also when a `project.info` lacks `github_url`), diff contains non-UTF-8 bytes that providers can't send (`non-utf8-diff`), `bug.info` / `bug_patch.txt` can't be read (`unreadable: ...`), anything else from git (`git-error: ...`).

## File structure

```
src/whippletree/datasets/bugsinpy.py   NEW  patch parsing, padding builder, clone/worktree, load_bugsinpy
src/whippletree/cli.py                 MOD  bugsinpy choice, (cases, skipped) plumbing, header + report line
tests/gitrepo.py                       NEW  helpers to build throwaway git repos in tmp_path
tests/test_bugsinpy_patch.py           NEW  parse_patch_ranges, touches_tests (pure)
tests/test_bugsinpy_padding.py         NEW  pick_base, apply_onto, build_padded (fixture repos)
tests/test_bugsinpy_loader.py          NEW  load_bugsinpy end to end against local fixture repos
tests/test_cli.py                      MOD  skips reach header and report
CLAUDE.md, README.md                   MOD  bugsinpy commands, cache location
results/2026-11-xx-bugsinpy-m1.md      NEW  curated Done-when summary (Task 7)
```

## Task overview

| # | Task | Produces |
| --- | ------ | ---------- |
| 1 | Patch parsing | `parse_patch_ranges`, `touches_tests` |
| 2 | Base picking | `tests/gitrepo.py`, `changed_lines`, `pick_base`, `SkipCase`, `GitError` |
| 3 | Padded diff | `apply_onto`, `build_padded` |
| 4 | Loader | `Skip`, `read_info`, `ensure_clone`, `ensure_checkout`, `build_case`, `load_bugsinpy` |
| 5 | CLI | `--dataset bugsinpy`, skips in header + report |
| 6 | Docs | CLAUDE.md, README.md |
| 7 | Done-when runs | results summary (manual, spends money) |

---

### Task 1: Patch parsing (pure)

**Files:** create `src/whippletree/datasets/bugsinpy.py`; test `tests/test_bugsinpy_patch.py`

**Interface:**

```python
def parse_patch_ranges(patch: str) -> tuple[Range, ...]:
    """One Range per contiguous change run in the fix (B -> F), in B's (pre-image) line numbers.

    A run with removed lines is kind="modification" spanning those lines. A run with only
    added lines is kind="deletion" at the line before the insertion (clamped to 1). Context
    lines end a run. Files the fix creates (--- /dev/null) give no range.
    """

def touches_tests(patch: str) -> bool:
    """True if any --- a/ or +++ b/ path looks like test code or test data."""
```

**Gotchas:**

- Hunk header regex: `^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@`. A count of `0` (`-7,0`) means "insert after line 7", so the pre-image line counter starts at `start + 1`.
- File paths come from `--- a/<path>` (pre-image). Patches may lack `diff --git` lines: a `--- a/` or `--- /dev/null` line starts a new file even mid-patch.
- Ignore `\ No newline at end of file`. A bare empty line inside a hunk is context whose leading space got stripped.
- Test-path regex: `(^|/)(tests?|testing)/|(^|/)test_[^/]*$|_test\.py$`.

- [ ] **Step 1: Write the failing tests** - `tests/test_bugsinpy_patch.py`:

```python
"""Pure patch parsing for BugsInPy fix patches (B -> F)."""

import pytest

from whippletree.case import Range
from whippletree.datasets.bugsinpy import parse_patch_ranges, touches_tests


def _patch(*lines: str) -> str:
    # Built from a list so editors can't strip the meaningful leading spaces.
    return "\n".join(lines) + "\n"


def _header(path: str) -> list[str]:
    return [f"diff --git a/{path} b/{path}", "index 1111111..2222222 100644",
            f"--- a/{path}", f"+++ b/{path}"]


def test_modification_and_separated_changes_in_one_hunk():
    patch = _patch(*_header("pkg/rule.py"),
                   "@@ -12,8 +12,9 @@ def match(command):",
                   " ", " ", " def get_new_command(command):",
                   "-    a = 1", "-    a2 = 1", "+    a = 2",
                   "     command.output)[0]",
                   "+    guard()",
                   " ", "     return x")
    assert parse_patch_ranges(patch) == (
        Range("pkg/rule.py", 15, 16, "modification"),
        Range("pkg/rule.py", 17, 17, "deletion"),
    )


def test_add_only_hunk_is_zero_width_deletion_at_line_before():
    patch = _patch(*_header("f.py"),
                   "@@ -3,4 +3,6 @@ def f(x):",
                   " def f(x):", "+    if x is None:", "+        return 0", "     return x")
    assert parse_patch_ranges(patch) == (Range("f.py", 3, 3, "deletion"),)


def test_zero_context_add_uses_git_count_zero_convention():
    patch = _patch(*_header("f.py"), "@@ -7,0 +8,2 @@", "+a", "+b")
    assert parse_patch_ranges(patch) == (Range("f.py", 7, 7, "deletion"),)


def test_insert_at_top_of_file_clamps_to_line_1():
    patch = _patch(*_header("f.py"), "@@ -1,2 +1,3 @@", "+import os", " a", " b")
    assert parse_patch_ranges(patch) == (Range("f.py", 1, 1, "deletion"),)


def test_one_range_per_change_run_and_per_file_in_order():
    patch = _patch(*_header("a.py"),
                   "@@ -1,3 +1,3 @@", " x", "-y", "+Y", " z",
                   "@@ -20,3 +20,4 @@", " p", "+q", " r",
                   *_header("b.py"),
                   "@@ -5,2 +5,2 @@", "-m", "+M", " n")
    assert parse_patch_ranges(patch) == (
        Range("a.py", 2, 2),
        Range("a.py", 20, 20, "deletion"),
        Range("b.py", 5, 5),
    )


def test_multi_file_patch_without_diff_git_headers():
    patch = _patch("--- a/a.py", "+++ b/a.py", "@@ -1,2 +1,2 @@", "-x", "+X", " y",
                   "--- a/b.py", "+++ b/b.py", "@@ -4,2 +4,3 @@", " m", "+n", " o")
    assert parse_patch_ranges(patch) == (
        Range("a.py", 1, 1, "modification"),
        Range("b.py", 4, 4, "deletion"),
    )


def test_file_created_by_fix_has_no_range():
    patch = _patch("diff --git a/new.py b/new.py", "new file mode 100644",
                   "--- /dev/null", "+++ b/new.py", "@@ -0,0 +1,2 @@", "+a", "+b")
    assert parse_patch_ranges(patch) == ()


def test_file_deleted_by_fix_uses_preimage_path():
    patch = _patch("diff --git a/old.py b/old.py", "deleted file mode 100644",
                   "--- a/old.py", "+++ /dev/null", "@@ -1,2 +0,0 @@", "-a", "-b")
    assert parse_patch_ranges(patch) == (Range("old.py", 1, 2),)


def test_no_newline_marker_and_blank_context_are_harmless():
    patch = _patch(*_header("f.py"), "@@ -1,3 +1,3 @@", " a", "", "-c",
                   "\\ No newline at end of file", "+C", "\\ No newline at end of file")
    assert parse_patch_ranges(patch) == (Range("f.py", 3, 3),)


def test_empty_patch_has_no_ranges():
    assert parse_patch_ranges("") == ()


@pytest.mark.parametrize("path", ["tests/test_x.py", "test/units/foo.py", "pkg/test_util.py",
                                  "pkg/foo_test.py", "a/testing/b.py"])
def test_touches_tests_true(path):
    assert touches_tests(_patch(*_header(path), "@@ -1 +1 @@", "-a", "+b"))


@pytest.mark.parametrize("path", ["pkg/contest.py", "pkg/latest/x.py", "attest.py"])
def test_touches_tests_false(path):
    assert not touches_tests(_patch(*_header(path), "@@ -1 +1 @@", "-a", "+b"))
```

- [ ] **Step 2: Run, verify fail** - `uv run pytest tests/test_bugsinpy_patch.py -v` → `ModuleNotFoundError`.
- [ ] **Step 3: Implement** to the interface above. Module docstring: what a padded diff is (one paragraph).
- [ ] **Step 4: Run, verify pass** - `uv run pytest tests/test_bugsinpy_patch.py -v && uv run ruff check .`
- [ ] **Step 5: Commit** - `feat(bugsinpy): parse fix patches into ground-truth ranges`

---

### Task 2: Fixture repo helpers and base picking

**Files:** create `tests/gitrepo.py`; modify `bugsinpy.py`; test `tests/test_bugsinpy_padding.py`

**Interface:**

```python
MIN_LINES, MAX_LINES, MAX_WALK = 80, 250, 50

class SkipCase(Exception):
    """A case that can't be built. str(e) is the skip reason. Becomes a Skip; never sinks the load."""

class GitError(Exception):
    """A git command failed."""

def _git(repo: Path, *args: str, input: str | None = None, env: dict[str, str] | None = None) -> str:
    """Run git in repo, return stdout; raise GitError(f"git {args[0]}: {stderr}") on nonzero exit."""

def changed_lines(repo: Path, a: str, b: str) -> int:
    """Added + deleted lines between two tree-ishes (git diff --numstat). Binary files count 0."""

def pick_base(repo: Path, buggy: str, min_lines: int = MIN_LINES, max_lines: int = MAX_LINES,
              max_walk: int = MAX_WALK) -> tuple[str, tuple[str, ...]]:
    """(base, commits) for the smallest K whose B~K..B reaches min_lines.

    commits are B~K..B's K commits, oldest first (B last). Walks first-parent from B, at most
    max_walk commits. Raises SkipCase: "no-history" (B is a root), "bug-commit-over-cap"
    (K=1 already > max_lines), "padding-under-min-lines" (cap, root, or max_walk reached first).
    """
```

**Gotchas:**

- Always pass `-c core.quotePath=false` to git, and for every diff/numstat use `--no-color --no-ext-diff --no-renames --src-prefix=a/ --dst-prefix=b/` (define once as `_DIFF_FLAGS`). The user's git config must not change the diff.
- History: `git rev-list --first-parent --max-count=<max_walk+1> B` → `[B, B~1, ...]`; base for K is `chain[K]`.

- [ ] **Step 1: Write the fixture helper** - `tests/gitrepo.py` (test support, given in full):

```python
"""Throwaway git repos for tests. Real git, no network."""

import subprocess
from pathlib import Path


def git(repo: Path, *args: str, input: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, input=input, check=True,
                          capture_output=True, text=True).stdout


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for key, value in [("user.email", "t@example.com"), ("user.name", "t"),
                       ("commit.gpgsign", "false")]:
        git(path, "config", key, value)
    return path


def commit(repo: Path, files: dict[str, str], msg: str = "c") -> str:
    """Write files (path -> content), commit everything, return the new sha."""
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").strip()


def lines(n: int, prefix: str = "x") -> str:
    return "".join(f"{prefix}{i}\n" for i in range(n))


APP_BUGGY = "def f(x):\n    return x + 2\n"
APP_FIXED = "def f(x):\n    return x + 1\n"


def padded_history(path: Path, bug_at: int = 0, b_size: int = 30) -> dict[str, str]:
    """c0 (app.py) -> c1, c2 (30-line pad files) -> B (b_size-line pad) -> F (fix).

    bug_at picks the commit that turns app.py's `x` into the buggy `x + 2`
    (0 = c0, 2 = c2, 3 = B). Returns shas plus the B -> F fix patch.
    """
    repo = init_repo(path)
    early = APP_BUGGY if bug_at == 0 else "def f(x):\n    return x\n"
    shas = {"c0": commit(repo, {"app.py": early})}
    shas["c1"] = commit(repo, {"pad1.py": lines(30, "a")})
    shas["c2"] = commit(repo, {"pad2.py": lines(30, "b"),
                               **({"app.py": APP_BUGGY} if bug_at == 2 else {})})
    shas["B"] = commit(repo, {"pad3.py": lines(b_size, "c"),
                              **({"app.py": APP_BUGGY} if bug_at == 3 else {})})
    shas["F"] = commit(repo, {"app.py": APP_FIXED})
    shas["patch"] = git(repo, "diff", shas["B"], shas["F"])
    return shas
```

- [ ] **Step 2: Write the failing tests** - `tests/test_bugsinpy_padding.py`:

```python
"""Padding builder against small fixture repos."""

import pytest

from tests.gitrepo import commit, init_repo, lines, padded_history
from whippletree.datasets.bugsinpy import SkipCase, changed_lines, pick_base


def test_changed_lines_counts_adds_and_deletes(tmp_path):
    s = padded_history(tmp_path / "r")
    assert changed_lines(tmp_path / "r", s["c1"], s["B"]) == 60
    assert changed_lines(tmp_path / "r", s["B"], s["F"]) == 2


def test_picks_smallest_k_reaching_min_lines(tmp_path):
    s = padded_history(tmp_path / "r")
    # K=1 -> 30 lines, K=2 -> 60 >= 50: base is B~2 = c1.
    assert pick_base(tmp_path / "r", s["B"], min_lines=50) == (s["c1"], (s["c2"], s["B"]))


def test_walk_stops_before_over_cap_commit(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, {"app.py": "a\n"})
    c1 = commit(repo, {"big.py": lines(200)})
    c2 = commit(repo, {"p.py": lines(30)})
    b = commit(repo, {"q.py": lines(30)})
    # K=2 reaches 60 >= 50 before K=3 (big.py, 260 > 100) is ever walked.
    assert pick_base(repo, b, min_lines=50, max_lines=100) == (c1, (c2, b))


def test_short_history_under_min_lines_skips(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, {"app.py": "a\n"})
    b = commit(repo, {"p.py": lines(10)})
    with pytest.raises(SkipCase, match="padding-under-min-lines"):
        pick_base(repo, b, min_lines=80)


def test_over_cap_commit_blocking_min_lines_skips(tmp_path):
    repo = init_repo(tmp_path / "r")
    commit(repo, {"app.py": "a\n"})
    commit(repo, {"big.py": lines(200)})
    b = commit(repo, {"q.py": lines(30)})
    with pytest.raises(SkipCase, match="padding-under-min-lines"):
        pick_base(repo, b, min_lines=80, max_lines=100)


def test_max_walk_limits_history(tmp_path):
    s = padded_history(tmp_path / "r")
    with pytest.raises(SkipCase, match="padding-under-min-lines"):
        pick_base(tmp_path / "r", s["B"], min_lines=50, max_walk=1)


def test_bug_commit_over_cap_skips(tmp_path):
    s = padded_history(tmp_path / "r", b_size=300)
    with pytest.raises(SkipCase, match="bug-commit-over-cap"):
        pick_base(tmp_path / "r", s["B"])


def test_root_commit_has_no_history(tmp_path):
    repo = init_repo(tmp_path / "r")
    b = commit(repo, {"app.py": "a\n"})
    with pytest.raises(SkipCase, match="no-history"):
        pick_base(repo, b)
```

- [ ] **Step 3: Run, verify fail** - `uv run pytest tests/test_bugsinpy_padding.py -v` → `ImportError`.
- [ ] **Step 4: Implement** to the interface above.
- [ ] **Step 5: Run, verify pass** - `uv run pytest tests/test_bugsinpy_padding.py -v && uv run ruff check .`
- [ ] **Step 6: Commit** - `feat(bugsinpy): pick padding base by first-parent line budget`

---

### Task 3: Apply the fix onto the base and build the padded diff

**Files:** modify `bugsinpy.py`; test `tests/test_bugsinpy_padding.py` (append)

**Interface:**

```python
def apply_onto(repo: Path, base: str, patch: str) -> str | None:
    """Tree sha of `base` (commit or tree) with `patch` applied, or None if it doesn't apply.

    Uses a throwaway index (GIT_INDEX_FILE in a TemporaryDirectory): read-tree base,
    apply --cached (patch on stdin), write-tree. The repo's own index and checkout are untouched.
    """

def build_padded(repo: Path, buggy: str, patch: str, min_lines: int = MIN_LINES,
                 max_lines: int = MAX_LINES) -> tuple[str, Padding]:
    """`git diff X B` (X = pick_base's base + fix) and its Padding record.

    Raises SkipCase: anything from pick_base, "fix-does-not-apply", "padding-out-of-bounds"
    (final X..B size outside [min_lines, max_lines]). Padding.changed_lines is the X..B size.
    """
```

**Gotchas:**

- `git apply` rejects a patch without a final newline as corrupt; append one if missing.
- Only `apply --cached` failure means "doesn't apply" (return None). Let `read-tree` / `write-tree` failures raise `GitError`.

- [ ] **Step 1: Append the failing tests** - add `apply_onto, build_padded` to the bugsinpy import and `git` to the `tests.gitrepo` import, then:

```python
def test_apply_onto_returns_tree_or_none(tmp_path):
    s = padded_history(tmp_path / "r", bug_at=2)
    repo = tmp_path / "r"
    assert apply_onto(repo, s["c1"], s["patch"]) is None  # c1 has no `x + 2` yet
    tree = apply_onto(repo, s["c2"], s["patch"])
    assert tree is not None
    assert "return x + 1" in git(repo, "show", f"{tree}:app.py")
    assert git(repo, "status", "--porcelain") == ""  # real index and checkout untouched


def test_apply_onto_tolerates_missing_final_newline(tmp_path):
    s = padded_history(tmp_path / "r")
    assert apply_onto(tmp_path / "r", s["B"], s["patch"].rstrip("\n")) is not None


def test_build_padded_diff_and_record(tmp_path):
    s = padded_history(tmp_path / "r")
    diff, padding = build_padded(tmp_path / "r", s["B"], s["patch"], min_lines=50)
    assert padding.base == s["c1"]
    assert padding.commits == (s["c2"], s["B"])
    assert padding.changed_lines == 62  # 60 padding + the reverted fix (1 del, 1 add)
    assert "-    return x + 1\n+    return x + 2" in diff  # the fix, played backwards
    assert "+++ b/pad2.py" in diff and "+++ b/pad3.py" in diff
    assert "pad1.py" not in diff  # already in the base


def test_build_padded_post_image_equals_buggy(tmp_path):
    s = padded_history(tmp_path / "r")
    repo = tmp_path / "r"
    diff, padding = build_padded(repo, s["B"], s["patch"], min_lines=50)
    x = apply_onto(repo, padding.base, s["patch"])
    assert apply_onto(repo, x, diff) == git(repo, "rev-parse", f"{s['B']}^{{tree}}").strip()


def test_skips_when_fix_wont_apply_at_base(tmp_path):
    # Bug introduced at c2, inside the padding: the fix can't apply at base c1.
    s = padded_history(tmp_path / "r", bug_at=2)
    with pytest.raises(SkipCase, match="fix-does-not-apply"):
        build_padded(tmp_path / "r", s["B"], s["patch"], min_lines=50)


def test_skips_when_final_diff_over_max(tmp_path):
    s = padded_history(tmp_path / "r")
    # B~2..B is 60 (fits max 61); the reverted fix adds 2 -> 62 > 61.
    with pytest.raises(SkipCase, match="padding-out-of-bounds"):
        build_padded(tmp_path / "r", s["B"], s["patch"], min_lines=50, max_lines=61)
```

- [ ] **Step 2: Run, verify fail** - `uv run pytest tests/test_bugsinpy_padding.py -v` → `ImportError`.
- [ ] **Step 3: Implement** to the interface above.
- [ ] **Step 4: Run, verify pass** - `uv run pytest tests/test_bugsinpy_padding.py tests/test_bugsinpy_patch.py -v && uv run ruff check .`
- [ ] **Step 5: Commit** - `feat(bugsinpy): build padded diffs via a throwaway index`

---

### Task 4: Loader - metadata, clones, worktrees, skips

**Files:** modify `bugsinpy.py`; test `tests/test_bugsinpy_loader.py`

BugsInPy layout (verified against `soarsmu/BugsInPy` master): `projects/<name>/project.info` has `github_url="..."` (sometimes with a trailing `/`); `projects/<name>/bugs/<n>/bug.info` has `buggy_commit_id="..."`; `bug_patch.txt` is the B -> F source diff. `.info` files may lack a trailing newline. Bug dirs are numeric.

**Interface:**

```python
CACHE = Path.home() / ".cache" / "whippletree" / "bugsinpy"
METADATA_URL = "https://github.com/soarsmu/BugsInPy.git"
DEFAULT_PROJECTS = ("PySnooper", "cookiecutter", "httpie", "sanic", "tqdm", "thefuck")

@dataclass(frozen=True)
class Skip:
    id: str
    reason: str

def read_info(path: Path) -> dict[str, str]:
    """BugsInPy .info files: key="value" lines (spaces around = allowed); other lines ignored."""

def ensure_clone(url: str, dest: Path, *extra: str) -> Path:
    """Clone url to dest once (extra = clone flags); reuse if dest/.git exists.
    Wipe a partial dest before and after a failed clone. Print "whippletree: cloning <url>" to stderr."""

def ensure_checkout(repo: Path, dest: Path, commit: str) -> Path:
    """Detached worktree of repo at commit. Reuse if HEAD already matches; otherwise wipe dest,
    `git worktree prune`, then `git worktree add --force --detach`."""

def build_case(case_id: str, repo: Path, bug_dir: Path, checkout: Path,
               min_lines: int = MIN_LINES, max_lines: int = MAX_LINES) -> Case:
    """One padded case, checkout at B. Raises SkipCase. Check order: no-ground-truth,
    patch-touches-tests, commit-missing, patch-does-not-apply-to-buggy, build_padded's reasons,
    bug-not-in-diff. Create the worktree last, so skipped cases leave no checkout behind."""

def load_bugsinpy(cache: Path = CACHE, projects: tuple[str, ...] = DEFAULT_PROJECTS,
                  metadata_url: str = METADATA_URL, min_lines: int = MIN_LINES,
                  max_lines: int = MAX_LINES, case_id: str | None = None,
                  limit: int | None = None) -> tuple[list[Case], list[Skip]]:
    """Cases in (project, numeric bug) order, plus a Skip for each attempted case that failed.

    limit: stop as soon as that many cases have built. case_id ("bugsinpy/<proj>/<n>"):
    build only that bug, from any BugsInPy project; unknown id -> ([], []).
    """
```

**Gotchas:**

- Metadata clone: `--depth 1`. Project clones: `--filter=blob:none` (blobs fetched lazily by worktree/apply). Local-path clones in tests warn that these flags are ignored; they still succeed.
- `bug-not-in-diff`: reuse `whippletree.baseline.changed_lines(diff)` (import it under another name; it clashes with ours). Each range needs at least one `(file, line)` from it inside `[start, end]`.
- Resolve the buggy sha with `git rev-parse --verify <sha>^{commit}`; failure → `commit-missing`.
- Clone failure → one `Skip(id, "clone-failed")` per bug of that project. `SkipCase` → `Skip(id, str(e))`; `GitError` → `Skip(id, f"git-error: {e}")`.

- [ ] **Step 1: Write the failing tests** - `tests/test_bugsinpy_loader.py`:

```python
"""load_bugsinpy end to end, against local fixture repos (no network)."""

from pathlib import Path

from tests.gitrepo import commit, git, init_repo, padded_history
from whippletree.case import Range
from whippletree.datasets.bugsinpy import Skip, load_bugsinpy, read_info

TEST_PATCH = ("diff --git a/tests/test_app.py b/tests/test_app.py\n"
              "--- a/tests/test_app.py\n+++ b/tests/test_app.py\n"
              "@@ -1 +1 @@\n-a\n+b\n")


def _metadata(tmp_path: Path, project_url: str, bugs: dict[str, tuple[str, str]]) -> Path:
    """A fake BugsInPy repo: bugs maps bug number -> (buggy sha, patch)."""
    meta = init_repo(tmp_path / "meta")
    files = {"projects/demo/project.info": f'github_url="{project_url}"\nstatus="OK"'}
    for n, (sha, patch) in bugs.items():
        files[f"projects/demo/bugs/{n}/bug.info"] = (
            f'python_version="3.8.3"\nbuggy_commit_id="{sha}"\nfixed_commit_id="x"')
        files[f"projects/demo/bugs/{n}/bug_patch.txt"] = patch
    commit(meta, files)
    return meta


def _load(tmp_path, bugs, project_url=None, **kwargs):
    s = padded_history(tmp_path / "upstream")
    meta = _metadata(tmp_path, project_url or str(tmp_path / "upstream"),
                     {n: (sha or s["B"], patch or s["patch"]) for n, (sha, patch) in bugs.items()})
    cases, skipped = load_bugsinpy(cache=tmp_path / "cache", projects=("demo",),
                                   metadata_url=str(meta), min_lines=50, **kwargs)
    return s, cases, skipped


def test_read_info_handles_quotes_and_missing_newline(tmp_path):
    p = tmp_path / "bug.info"
    p.write_text('a="1"\nb = "two words"\nnot a pair')
    assert read_info(p) == {"a": "1", "b": "two words"}


def test_builds_case_with_checkout_at_buggy(tmp_path):
    s, cases, skipped = _load(tmp_path, {"1": (None, None)})
    assert skipped == []
    (case,) = cases
    assert case.id == "bugsinpy/demo/1"
    assert case.dataset == "bugsinpy"
    assert case.ground_truth == (Range("app.py", 2, 2),)
    assert case.padding.base == s["c1"]
    assert git(case.checkout_path, "rev-parse", "HEAD").strip() == s["B"]
    assert "return x + 2" in (case.checkout_path / "app.py").read_text()
    assert "+    return x + 2" in case.diff


def test_bad_cases_are_skipped_with_reasons_not_raised(tmp_path):
    _, cases, skipped = _load(tmp_path, {
        "1": (None, None),
        "2": (None, TEST_PATCH),
        "3": ("0" * 40, None),
        "4": (None, "not a patch\n"),
    })
    assert [c.id for c in cases] == ["bugsinpy/demo/1"]
    assert skipped == [Skip("bugsinpy/demo/2", "patch-touches-tests"),
                       Skip("bugsinpy/demo/3", "commit-missing"),
                       Skip("bugsinpy/demo/4", "no-ground-truth")]
    assert not (tmp_path / "cache" / "checkouts" / "demo-2").exists()


def test_bugs_sorted_numerically(tmp_path):
    _, cases, _ = _load(tmp_path, {"10": (None, None), "2": (None, None)})
    assert [c.id for c in cases] == ["bugsinpy/demo/2", "bugsinpy/demo/10"]


def test_limit_stops_early(tmp_path):
    _, cases, skipped = _load(tmp_path, {"1": (None, TEST_PATCH), "2": (None, None),
                                         "3": (None, None)}, limit=1)
    assert [c.id for c in cases] == ["bugsinpy/demo/2"]
    assert skipped == [Skip("bugsinpy/demo/1", "patch-touches-tests")]
    assert not (tmp_path / "cache" / "checkouts" / "demo-3").exists()


def test_case_id_builds_one_case_from_any_project(tmp_path):
    _load(tmp_path, {"1": (None, None), "3": (None, None)}, limit=1)
    cases, skipped = load_bugsinpy(cache=tmp_path / "cache", projects=("other",),
                                   metadata_url=str(tmp_path / "meta"), min_lines=50,
                                   case_id="bugsinpy/demo/3")
    assert [c.id for c in cases] == ["bugsinpy/demo/3"]
    assert skipped == []
    assert load_bugsinpy(cache=tmp_path / "cache", metadata_url=str(tmp_path / "meta"),
                         case_id="bugsinpy/nope/1") == ([], [])


def test_second_load_reuses_cache(tmp_path):
    _, first, _ = _load(tmp_path, {"1": (None, None)})
    again, skipped = load_bugsinpy(cache=tmp_path / "cache", projects=("demo",),
                                   metadata_url=str(tmp_path / "meta"), min_lines=50)
    assert skipped == []
    assert again == first


def test_clone_failure_skips_whole_project(tmp_path):
    _, cases, skipped = _load(tmp_path, {"1": (None, None)},
                              project_url=str(tmp_path / "nope"))
    assert cases == []
    assert skipped == [Skip("bugsinpy/demo/1", "clone-failed")]
    assert not (tmp_path / "cache" / "repos" / "demo").exists()


def test_patch_that_does_not_fit_buggy_is_skipped(tmp_path):
    other_patch = ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
                   "@@ -1 +1 @@\n-nothing like this\n+here\n")
    _, _, skipped = _load(tmp_path, {"1": (None, other_patch)})
    assert skipped == [Skip("bugsinpy/demo/1", "patch-does-not-apply-to-buggy")]
```

- [ ] **Step 2: Run, verify fail** - `uv run pytest tests/test_bugsinpy_loader.py -v` → `ImportError`.
- [ ] **Step 3: Implement** to the interface above.
- [ ] **Step 4: Run, verify pass** - `uv run pytest && uv run ruff check .`
- [ ] **Step 5: Commit** - `feat(bugsinpy): load cases with cached clones and skip reasons`

---

### Task 5: CLI - `--dataset bugsinpy`, skips in header and report

**Files:** modify `src/whippletree/cli.py`; test `tests/test_cli.py` (append)

**Changes:**

- Import `load_bugsinpy` into `cli` (module-level name, so tests can monkeypatch `cli.load_bugsinpy`). `DATASETS = ("bugsinpy", "seeded")`.
- `load_cases(dataset, case_id, limit) -> (cases, skipped)`: bugsinpy calls `load_bugsinpy(case_id=case_id, limit=limit)`; seeded keeps today's filter/slice and returns `[]` skips.
- `select_cases` returns `(cases, skipped)`; if any skips, print `whippletree: skipped N <dataset> cases at load (reasons in the trace header)` to stderr. The "no cases match" error is unchanged.
- `_base_header(..., skipped)` adds `skipped=[asdict(s) for s in skipped]`. Update `cmd_review` / `cmd_baseline` to pass it.
- `format_metrics`: when `header.get("skipped")` is non-empty, append `skipped at load: N (reason n, ...)`. Group by the reason text before the first `:`, sorted by reason.
- Run `grep -rn "load_cases\|select_cases\|_base_header" src tests` and update every caller.

- [ ] **Step 1: Append the failing tests** to `tests/test_cli.py`:

```python
def test_bugsinpy_skips_reach_header_and_report(tmp_path, capsys, monkeypatch):
    from whippletree.datasets.bugsinpy import Skip
    fake = [replace(c, id=c.id.replace("seeded", "bugsinpy"), dataset="bugsinpy")
            for c in load_seeded()]
    skips = [Skip("bugsinpy/demo/7", "patch-touches-tests"),
             Skip("bugsinpy/demo/8", "git-error: git diff: boom"),
             Skip("bugsinpy/demo/9", "git-error: git apply: bang")]
    monkeypatch.setattr(cli, "load_bugsinpy", lambda **kw: (fake, skips))
    runs = str(tmp_path / "runs")
    assert cli.main(["run", "baseline", "--dataset", "bugsinpy", "--runs-dir", runs]) == 0
    captured = capsys.readouterr()
    run_id = captured.out.strip().splitlines()[-1]
    assert "skipped 3 bugsinpy cases" in captured.err
    header = read_trace(tmp_path / "runs" / f"{run_id}.jsonl")[0]
    assert header["skipped"][0] == {"id": "bugsinpy/demo/7", "reason": "patch-touches-tests"}
    cli.main(["report", run_id, "--runs-dir", runs])
    out = capsys.readouterr().out
    assert "skipped at load: 3 (git-error 2, patch-touches-tests 1)" in out
    assert "cases 2 scored" in out


def test_bugsinpy_passes_limit_and_case_through(tmp_path, capsys, monkeypatch):
    seen = {}
    fake = [replace(load_seeded()[0], id="bugsinpy/demo/1", dataset="bugsinpy")]
    monkeypatch.setattr(cli, "load_bugsinpy", lambda **kw: (seen.update(kw) or (fake, [])))
    runs = str(tmp_path / "runs")
    cli.main(["run", "baseline", "--dataset", "bugsinpy", "--limit", "5", "--runs-dir", runs])
    assert seen == {"case_id": None, "limit": 5}


def test_seeded_run_has_no_skip_line(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    cli.main(["run", "baseline", "--dataset", "seeded", "--runs-dir", runs])
    run_id = _run_id(capsys)
    cli.main(["report", run_id, "--runs-dir", runs])
    assert "skipped at load" not in capsys.readouterr().out
```

- [ ] **Step 2: Run, verify fail** - `uv run pytest tests/test_cli.py -k "bugsinpy or skip" -v` → `AttributeError: ... no attribute 'load_bugsinpy'`.
- [ ] **Step 3: Implement** the changes above.
- [ ] **Step 4: Run, verify pass** - `uv run pytest && uv run ruff check .` (all pre-existing CLI tests too).
- [ ] **Step 5: Commit** - `feat(cli): --dataset bugsinpy, record and report load-time skips`

---

### Task 6: Docs

**Files:** `CLAUDE.md`, `README.md`

- [ ] **Step 1: `CLAUDE.md`**: change the intro's "BugsInPy is next" to say M1 runs on the seeded set and BugsInPy (padded diffs). Add to Commands:

```bash
uv run whippletree run baseline --dataset bugsinpy --limit 24   # first run clones into ~/.cache/whippletree/bugsinpy/
uv run whippletree run review --dataset bugsinpy --limit 24 --model openrouter:google/gemini-2.5-pro
```

Add to "Where things are": the BugsInPy cache path (metadata, blobless clones, one worktree per case at the buggy commit; delete to rebuild).

- [ ] **Step 2: `README.md`**: add the same commands and one cache sentence to its existing usage section, matching its style. One line per paragraph, no hard wraps.
- [ ] **Step 3: Commit** - `docs: bugsinpy dataset usage and cache location`

---

### Task 7: Done-when runs (manual, spends money - confirm the second model and budget with the user first)

**Files:** create `results/2026-11-xx-bugsinpy-m1.md` (date of the run)

- [ ] **Step 1: Build and check yield** - `uv run whippletree run baseline --dataset bugsinpy --limit 24`, then `report` it: must show `cases 24 scored`. If fewer than 20 build, add projects to `DEFAULT_PROJECTS` (next smallest: `black`, `fastapi`), commit, rerun. Strict bounds and no fallback (Decisions 2-3) may cost yield; the skip line shows where.
- [ ] **Step 2: Spot-check two cases by hand** (not optional):

```bash
uv run python -c "
from whippletree.datasets.bugsinpy import load_bugsinpy
cases, skipped = load_bugsinpy(limit=24)
for c in cases[:2]:
    print(c.id, c.padding, c.ground_truth)
    print(c.diff[:3000])
print(len(cases), 'cases;', len(skipped), 'skipped')
"
```

For each one, confirm that the diff reads like a PR (several innocent hunks), that the reverted fix is in it, and that each ground-truth line in the checkout holds the buggy code (`sed -n '<start>,<end>p' <checkout>/<file>`).

- [ ] **Step 3: Review runs** with the same `--limit 24`, so `dataset_hash` matches the baseline:

```bash
uv run whippletree run review --dataset bugsinpy --limit 24 --model openrouter:google/gemini-2.5-pro --routing google-vertex
uv run whippletree run review --dataset bugsinpy --limit 24 --model <second model, user's pick>
```

- [ ] **Step 4: Report** - `uv run whippletree report <baseline-id> <model1-id> <model2-id>`: three blocks, no `dataset_hash differs` warning.
- [ ] **Step 5: Write the results file**: run ids, models, the three report blocks verbatim (scrub home-dir paths), skip reasons and counts, and a few sentences covering two questions. Does each model beat random? How does recall by kind compare (deletion vs modification, the reversal-artifact check from the spec's risks)?
- [ ] **Step 6: Commit and close** - `results: M1 BugsInPy runs vs random baseline`, then `bd close whippletree-ial`.

---

## Self-review notes

- Spec coverage: padded diffs (Tasks 2-3), K by line budget with cap (Task 2), checkout at B, ground truth in B's lines with zero-width add-only ranges (Tasks 1, 4), skips counted with reasons into the trace (Tasks 4-5), padding in trace (runner already does it), cache location (Task 4), spec line 163 fixture tests including "post-image equals B" (Tasks 1-4), Done-when (Task 7).
- Deliberate deviation: no smaller-K fallback (Decision 2). The spec's "skip if only K=0 works" is covered by `fix-does-not-apply`.
- Not covered on purpose: SZZ realism subset (the spec lists it as a later check).
