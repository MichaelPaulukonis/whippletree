"""BugsInPy loader: turns a real bug-fix commit into a padded-diff review case.

A padded diff is the PR-style diff the reviewer sees: the buggy commit B is diffed against an
older base X so the diff carries enough unrelated change to hide the bug among realistic noise.
Ground truth comes from the project's fix patch (buggy B -> fixed F), expressed in B's line
numbers, which are the head-side line numbers of the padded diff.
"""

import re

from whippletree.case import Range

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*$|_test\.py$")


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
