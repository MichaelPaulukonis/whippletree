"""BugsInPy loader: turns a real bug-fix commit into a padded-diff review case.

A padded diff is the PR-style diff the reviewer sees: the buggy commit B is diffed against an
older base X so the diff carries enough unrelated change to hide the bug among realistic noise.
Ground truth comes from the project's fix patch (buggy B -> fixed F), expressed in B's line
numbers, which are the head-side line numbers of the padded diff.
"""

import os
import re
import subprocess
from pathlib import Path

from whippletree.case import Range

MIN_LINES, MAX_LINES, MAX_WALK = 80, 250, 50

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*$|_test\.py$")
# The user's git config must not change the diff.
_DIFF_FLAGS = ("--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/")


class SkipCase(Exception):
    """A case that can't be built. str(e) is the skip reason. Becomes a Skip; never sinks the load."""


class GitError(Exception):
    """A git command failed."""


def parse_patch_ranges(patch: str) -> tuple[Range, ...]:
    """One Range per contiguous change run in the fix (B -> F), in B's (pre-image) line numbers.

    A run with removed lines is kind="modification" spanning those lines. A run with only
    added lines is kind="deletion" at the line before the insertion (clamped to 1). Context
    lines end a run. Files the fix creates (--- /dev/null) give no range.
    """
    ranges: list[Range] = []
    path: str | None = None
    old_ln = old_rem = new_rem = 0
    # Current run: first/last removed line (or None) and where an add-only run would sit.
    first_rm: int | None = None
    last_rm = 0
    add_at: int | None = None

    def flush() -> None:
        nonlocal first_rm, add_at
        if path is not None:
            if first_rm is not None:
                ranges.append(Range(path, first_rm, last_rm, "modification"))
            elif add_at is not None:
                at = max(add_at - 1, 1)
                ranges.append(Range(path, at, at, "deletion"))
        first_rm = add_at = None

    for line in patch.splitlines():
        in_hunk = old_rem > 0 or new_rem > 0
        if not in_hunk:
            if line.startswith("--- "):
                flush()
                name = line[4:].split("\t")[0]
                path = name[2:] if name.startswith("a/") else None
                continue
            m = _HUNK.match(line)
            if m:
                flush()
                start = int(m.group(1))
                old_rem = 1 if m.group(2) is None else int(m.group(2))
                new_rem = 1 if m.group(3) is None else int(m.group(3))
                # count 0: start is the line before the insertion
                old_ln = start + 1 if old_rem == 0 else start
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("-"):
            if first_rm is None:
                first_rm = old_ln
            last_rm = old_ln
            old_ln += 1
            old_rem -= 1
        elif line.startswith("+"):
            if add_at is None:
                add_at = old_ln
            new_rem -= 1
        else:  # context; a bare empty line is context whose leading space was stripped
            flush()
            old_ln += 1
            old_rem -= 1
            new_rem -= 1
        if old_rem <= 0 and new_rem <= 0:
            flush()
            old_rem = new_rem = 0
    flush()
    return tuple(ranges)


def touches_tests(patch: str) -> bool:
    """True if any --- a/ or +++ b/ path looks like test code or test data."""
    for line in patch.splitlines():
        if line.startswith(("--- a/", "+++ b/")) and _TEST_PATH.search(line[6:].split("\t")[0]):
            return True
    return False


def _git(repo: Path, *args: str, input: str | None = None, env: dict[str, str] | None = None) -> str:
    """Run git in repo, return stdout; raise GitError(f"git {args[0]}: {stderr}") on nonzero exit."""
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], cwd=repo, input=input,
        capture_output=True, text=True, env={**os.environ, **env} if env else None,
    )
    if proc.returncode != 0:
        raise GitError(f"git {args[0]}: {proc.stderr.strip()}")
    return proc.stdout


def changed_lines(repo: Path, a: str, b: str) -> int:
    """Added + deleted lines between two tree-ishes (git diff --numstat). Binary files count 0."""
    total = 0
    for row in _git(repo, "diff", "--numstat", *_DIFF_FLAGS, a, b).splitlines():
        added, deleted, _ = row.split("\t", 2)
        if added != "-":  # binary files show "-"
            total += int(added) + int(deleted)
    return total


def pick_base(repo: Path, buggy: str, min_lines: int = MIN_LINES, max_lines: int = MAX_LINES,
              max_walk: int = MAX_WALK) -> tuple[str, tuple[str, ...]]:
    """(base, commits) for the smallest K whose B~K..B reaches min_lines.

    commits are B~K..B's K commits, oldest first (B last). Walks first-parent from B, at most
    max_walk commits. Raises SkipCase: "no-history" (B is a root), "bug-commit-over-cap"
    (K=1 already > max_lines), "padding-under-min-lines" (cap, root, or max_walk reached first).
    """
    chain = _git(repo, "rev-list", "--first-parent", f"--max-count={max_walk + 1}", buggy).split()
    if len(chain) < 2:
        raise SkipCase("no-history")
    for k in range(1, len(chain)):
        n = changed_lines(repo, chain[k], buggy)
        if n > max_lines:
            raise SkipCase("bug-commit-over-cap" if k == 1 else "padding-under-min-lines")
        if n >= min_lines:
            return chain[k], tuple(reversed(chain[:k]))
    raise SkipCase("padding-under-min-lines")
