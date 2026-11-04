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
