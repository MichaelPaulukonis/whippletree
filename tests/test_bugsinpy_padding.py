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
