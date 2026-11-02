"""A reviewer that guesses: random changed lines. Sets the floor models must beat."""

import random
import re

from whippletree.case import Case, Finding

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff: str) -> list[tuple[str, int]]:
    """(file, head line) for every added line, plus the line before each removal point."""
    out = set()
    file, line = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            file = None if path == "/dev/null" else path.removeprefix("b/")
            continue
        if raw.startswith("--- "):
            continue
        m = _HUNK.match(raw)
        if m:
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
