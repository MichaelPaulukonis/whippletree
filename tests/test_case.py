from pathlib import Path

import pytest

from whippletree.case import Case, Finding, Padding, Range


def test_range_defaults_to_modification():
    assert Range("a.py", 3, 4).kind == "modification"


def test_range_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Range("a.py", 3, 3, kind="other")


def test_case_holds_ground_truth_and_optional_padding():
    case = Case(
        id="seeded/x",
        dataset="seeded",
        checkout_path=Path("/tmp/x"),
        diff="--- a/a.py\n+++ b/a.py\n",
        ground_truth=(Range("a.py", 1, 1),),
    )
    assert case.padding is None
    padded = Case(**{**case.__dict__, "padding": Padding("abc", ("d", "e"), 120)})
    assert padded.padding.changed_lines == 120


def test_finding_fields():
    f = Finding(file="a.py", line=2, claim="off by one", confidence=0.8)
    assert (f.file, f.line, f.confidence) == ("a.py", 2, 0.8)
