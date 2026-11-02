import pytest

from whippletree.case import Finding, Range
from whippletree.scoring import CaseRecord, aggregate, score

MOD = (Range("a.py", 20, 22),)


def f(line, file="a.py", conf=0.9):
    return Finding(file, line, "claim", conf)


@pytest.mark.parametrize("line, hit", [(21, True), (15, True), (27, True), (14, False),
                                       (28, False)])
def test_window_edges(line, hit):
    s = score([f(line)], MOD)
    assert s.found is hit
    assert (s.tp, s.fp) == ((1, 0) if hit else (0, 1))


def test_wrong_file_is_false_positive():
    assert (score([f(21, file="b.py")], MOD).fp) == 1


@pytest.mark.parametrize("name", ["b/a.py", "a/a.py", "./a.py"])
def test_diff_style_prefixes_still_match(name):
    assert score([f(21, file=name)], MOD).tp == 1


def test_second_hit_on_same_range_is_a_dupe_not_a_fp():
    s = score([f(20), f(22)], MOD)
    assert (s.tp, s.dupes, s.fp) == (1, 1, 0)


def test_no_findings():
    s = score([], MOD)
    assert (s.tp, s.fp, s.dupes, s.found) == (0, 0, 0, False)


@pytest.mark.parametrize("line, hit", [(2, True), (1, False), (12, True), (13, False)])
def test_zero_width_deletion_range(line, hit):
    assert score([f(line)], (Range("a.py", 7, 7, "deletion"),)).found is hit


def test_multiple_ranges_are_one_bug_for_recall():
    truth = (Range("a.py", 20, 20), Range("a.py", 90, 90))
    s = score([f(20), f(90)], truth)
    assert (s.tp, s.found) == (2, True)


def rec(findings, truth, tokens=1000, cost=0.10, errored=False, repeat=0, tool_errors=0,
        parse_failures=0):
    return CaseRecord(
        case_id="c", repeat=repeat, findings=tuple(findings), truth=truth,
        stop="error" if errored else "done", tokens=tokens, cost_usd=cost, cost_source="provider",
        tool_errors=tool_errors, parse_failures=parse_failures, errored=errored,
    )


def test_aggregate():
    records = [
        rec([f(21, conf=0.9), f(80, conf=0.3)], MOD, tokens=1000, cost=0.10, tool_errors=1),
        rec([], (Range("a.py", 7, 7, "deletion"),), tokens=500, cost=0.05, parse_failures=2),
        rec([], MOD, tokens=0, cost=0.0, errored=True),
    ]
    m = aggregate(records)
    assert (m.cases, m.errored) == (2, 1)
    assert m.recall == 0.5
    assert m.precision == 0.5
    assert m.f1 == 0.5
    assert m.cost_usd == pytest.approx(0.15)
    assert m.cost_per_tp == pytest.approx(0.15)
    assert m.tokens_per_tp == 1500
    assert (m.tool_errors, m.parse_failures) == (1, 2)
    assert m.recall_by_kind == {"modification": 1.0, "deletion": 0.0}
    assert m.pr_curve[0] == (0.0, 0.5, 0.5)
    assert m.pr_curve[1] == (0.5, 1.0, 0.5)


def test_unknown_cost_makes_run_cost_unknown():
    m = aggregate([rec([f(21)], MOD, cost=None)])
    assert m.cost_usd is None and m.cost_per_tp is None


def test_nothing_found_gives_no_per_tp_numbers():
    m = aggregate([rec([], MOD)])
    assert m.cost_per_tp is None and m.tokens_per_tp is None and m.f1 == 0.0


def test_case_record_round_trips_through_dict():
    from dataclasses import asdict
    r = rec([f(21)], MOD)
    assert CaseRecord.from_dict(asdict(r)) == r
