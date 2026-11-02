"""A reviewer that guesses: random changed lines. Sets the floor models must beat."""

import random
import re

from whippletree.case import Case, Finding

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff: str) -> list[tuple[str, int]]:
    """(file, head line) for every added line, plus the line before each removal point."""
    out = set()
    file, line = None, 0
    # ---/+++ are file headers only outside a hunk (also true before any diff --git line).
    # Written for git-style diffs: each file starts at a "diff --git" line, and a file with
    # no +++ line (e.g. a binary entry) must not inherit the previous file's name.
    in_header = True
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            in_header = True
            file = None
            continue
        if in_header and raw.startswith("+++ "):
            path = raw[4:].strip()
            file = None if path == "/dev/null" else path.removeprefix("b/")
            continue
        if in_header and raw.startswith("--- "):
            continue
        m = _HUNK.match(raw)
        if m:
            in_header = False
            line = int(m.group(1))
            continue
        if file is None:
            continue
        if raw.startswith("+"):
            out.add((file, line))
            line += 1
        elif raw.startswith("-"):
            out.add((file, max(line - 1, 1)))
        elif raw.startswith(" "):
            line += 1
    return sorted(out)


def baseline_findings(case: Case, k: int, rng: random.Random) -> list[Finding]:
    lines = changed_lines(case.diff)
    picks = rng.sample(lines, min(k, len(lines)))
    return [Finding(file, line, "baseline guess", 0.5) for file, line in sorted(picks)]
