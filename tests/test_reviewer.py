import pytest

from tests.fakes import FakeProvider, call, resp
from whippletree.case import Case, Finding
from whippletree.loop import Limits
from whippletree.roles.reviewer import (
    build_user_message,
    make_submit_tool,
    review,
    validate_findings,
)
from whippletree.tools.base import Submit, ToolError

GOOD = {"file": "a.py", "line": 3, "claim": "off by one", "confidence": 0.9}


def test_valid_findings():
    assert validate_findings({"findings": [GOOD]}) == [Finding("a.py", 3, "off by one", 0.9)]


def test_empty_list_is_valid():
    assert validate_findings({"findings": []}) == []


def test_integral_float_line_is_accepted_as_int():
    line = validate_findings({"findings": [{**GOOD, "line": 12.0}]})[0].line
    assert line == 12 and type(line) is int


def test_integer_confidence_is_accepted_as_float():
    assert validate_findings({"findings": [{**GOOD, "confidence": 1}]})[0].confidence == 1.0


@pytest.mark.parametrize(
    "args, message",
    [
        ({}, "must be a list"),
        ({"findings": "none"}, "must be a list"),
        ({"findings": ["x"]}, "must be an object"),
        ({"findings": [{"file": "a.py"}]}, "missing: line, claim, confidence"),
        ({"findings": [{**GOOD, "file": ""}]}, "'file'"),
        ({"findings": [{**GOOD, "line": True}]}, "'line'"),
        ({"findings": [{**GOOD, "line": 0}]}, "'line'"),
        ({"findings": [{**GOOD, "line": "3"}]}, "'line'"),
        ({"findings": [{**GOOD, "line": 12.5}]}, "'line'"),
        ({"findings": [{**GOOD, "line": 0.0}]}, "'line'"),
        ({"findings": [{**GOOD, "line": float("inf")}]}, "'line'"),
        ({"findings": [{**GOOD, "claim": ""}]}, "'claim'"),
        ({"findings": [{**GOOD, "confidence": 1.5}]}, "'confidence'"),
        ({"findings": [{**GOOD, "confidence": "high"}]}, "'confidence'"),
    ],
)
def test_invalid_findings(args, message):
    with pytest.raises(ToolError, match=message):
        validate_findings(args)


def test_submit_tool_is_terminal_and_returns_submit():
    tool = make_submit_tool()
    assert tool.terminal
    assert tool.fn({"findings": [GOOD]}) == Submit([Finding("a.py", 3, "off by one", 0.9)])


@pytest.fixture
def case(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    return Case(id="t/1", dataset="t", checkout_path=tmp_path, diff="+x = 1", ground_truth=())


def test_review_end_to_end(case):
    provider = FakeProvider([
        resp(calls=[call("read_file", {"path": "a.py"})]),
        resp(calls=[call("submit_findings", {"findings": [{**GOOD, "confidence": "bad"}]})]),
        resp(calls=[call("submit_findings", {"findings": [GOOD]})]),
    ])
    result = review(case, provider, "m")
    assert result.findings == [Finding("a.py", 3, "off by one", 0.9)]
    assert result.loop.stop == "done"
    assert result.parse_failures == 1
    first_prompt = provider.seen[0]
    assert first_prompt[0]["role"] == "system"
    assert "+x = 1" in first_prompt[1]["content"]
    assert any(m.get("content") == "1\tx = 1" for m in provider.seen[1])


def test_review_without_submission_scores_no_findings(case):
    result = review(case, FakeProvider([resp("looks fine"), resp("still fine")]), "m")
    assert result.loop.stop == "no_submit"
    assert result.findings == []


def test_system_prompt_states_the_step_limit(case):
    provider = FakeProvider([resp(calls=[call("submit_findings", {"findings": []})])])
    review(case, provider, "m", limits=Limits(max_steps=7))
    assert "at most 7 model turns" in provider.seen[0][0]["content"]


def test_system_prompt_uses_default_limits(case):
    provider = FakeProvider([resp(calls=[call("submit_findings", {"findings": []})])])
    review(case, provider, "m")
    assert f"at most {Limits().max_steps} model turns" in provider.seen[0][0]["content"]


def test_diff_fence_is_longer_than_any_backtick_run_in_it(case):
    diff = "+```\n+y = '````'"
    msg = build_user_message(Case(id="t", dataset="t", checkout_path=case.checkout_path,
                                  diff=diff, ground_truth=()))
    assert msg.endswith(f"`````diff\n{diff}\n`````")
    assert build_user_message(case).endswith("```diff\n+x = 1\n```")


def test_system_prompt_tolerates_literal_braces(monkeypatch):
    import whippletree.roles.reviewer as reviewer
    monkeypatch.setattr(reviewer, "SYSTEM_PROMPT", 'e.g. {"file": "a.py"}; {max_steps} turns')
    assert reviewer.build_system_prompt(Limits(max_steps=4)) == 'e.g. {"file": "a.py"}; 4 turns'
