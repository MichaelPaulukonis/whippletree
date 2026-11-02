import json

import pytest

from whippletree.case import Range
from whippletree.datasets.seeded import SEEDED_ROOT, load_seeded, tree_diff


def test_loads_both_cases_in_order():
    cases = load_seeded()
    assert [c.id for c in cases] == ["seeded/missing-none-check", "seeded/pagination-off-by-one"]
    assert all(c.dataset == "seeded" and c.checkout_path.is_dir() for c in cases)


def test_ground_truth_parsed():
    case = {c.id: c for c in load_seeded()}["seeded/missing-none-check"]
    assert case.ground_truth == (Range("config.py", 7, 7, "deletion"),)


def test_diff_has_repo_relative_headers():
    case = load_seeded()[1]
    assert "--- a/catalog.py" in case.diff
    assert "+++ b/catalog.py" in case.diff
    assert "+    start = page_number * page_size" in case.diff


def test_seeded_truth_points_at_bug_line():
    """Guards every hand-written case: each range's start line holds the expected text."""
    for case_dir in sorted(p for p in SEEDED_ROOT.iterdir() if p.is_dir()):
        truth = json.loads((case_dir / "truth.json").read_text())
        for r in truth["ranges"]:
            lines = (case_dir / "after" / r["file"]).read_text().splitlines()
            assert r["expect"] in lines[r["start"] - 1], f"{case_dir.name}: {r}"


def test_tree_diff_on_temp_trees(tmp_path):
    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    (tmp_path / "before" / "x.py").write_text("a\n")
    (tmp_path / "after" / "x.py").write_text("b\n")
    diff = tree_diff(tmp_path / "before", tmp_path / "after")
    assert "--- a/x.py\n+++ b/x.py" in diff
    assert "-a\n+b" in diff


def test_tree_diff_identical_trees_is_empty(tmp_path):
    for side in ("before", "after"):
        (tmp_path / side).mkdir()
        (tmp_path / side / "x.py").write_text("same\n")
    assert tree_diff(tmp_path / "before", tmp_path / "after") == ""


def test_tree_diff_leaves_content_paths_alone(tmp_path):
    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    (tmp_path / "before" / "x.py").write_text("p = 'data/before/x'\n-- a/before/q\n")
    (tmp_path / "after" / "x.py").write_text("p = 'a/before/y'\nq = 'b/after/z'\n")
    diff = tree_diff(tmp_path / "before", tmp_path / "after")
    assert "--- a/x.py\n+++ b/x.py" in diff
    assert "-p = 'data/before/x'\n" in diff
    assert "\n--- a/before/q\n" in diff  # removed line that looks like a header
    assert "+p = 'a/before/y'\n+q = 'b/after/z'\n" in diff


def test_tree_diff_rewrites_rename_and_new_file_headers(tmp_path):
    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    (tmp_path / "before" / "old name.py").write_text("same\n" * 5)
    (tmp_path / "after" / "new name.py").write_text("same\n" * 5)
    (tmp_path / "after" / "é.py").write_text("x\n")
    diff = tree_diff(tmp_path / "before", tmp_path / "after")
    assert "before/" not in diff and "after/" not in diff
    assert "rename from old name.py" in diff
    assert "rename to new name.py" in diff
    assert "+++ b/é.py" in diff


def test_tree_diff_requires_sibling_trees(tmp_path):
    (tmp_path / "x" / "before").mkdir(parents=True)
    (tmp_path / "after").mkdir()
    with pytest.raises(ValueError):
        tree_diff(tmp_path / "x" / "before", tmp_path / "after")
