"""Padding builder against small fixture repos."""

import pytest

from tests.gitrepo import commit, git, init_repo, lines, padded_history
from whippletree.datasets.bugsinpy import (
    SkipCase,
    _git,
    apply_onto,
    build_padded,
    changed_lines,
    pick_base,
)


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


def test_git_tolerates_non_utf8_content(tmp_path):
    repo = init_repo(tmp_path / "r")
    (repo / "l.py").write_bytes("x = 'caf\xe9'\n".encode("latin-1"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "latin1")
    assert isinstance(_git(repo, "show", "HEAD:l.py"), str)


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
