from pathlib import Path

import pytest

from whippletree.case import Range
from whippletree.errors import WhippletreeError
from whippletree.traces import TraceWriter, new_run_id, read_trace


def test_write_and_read_back(tmp_path):
    path = tmp_path / "runs" / "r.jsonl"
    with TraceWriter(path) as trace:
        trace.write("header", run_id="r", where=Path("/x"))
        trace.write("case", truth=(Range("a.py", 1, 2),))
    events = read_trace(path)
    assert events[0] == {"kind": "header", "run_id": "r", "where": "/x"}
    assert events[1]["truth"] == [{"file": "a.py", "start": 1, "end": 2, "kind": "modification"}]


def test_run_ids_are_unique_and_sortable():
    a, b = new_run_id(), new_run_id()
    assert a != b
    assert a[:8].isdigit()


def test_existing_trace_is_not_overwritten(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text("keep")
    with pytest.raises(WhippletreeError, match="already exists"):
        TraceWriter(path)
    assert path.read_text() == "keep"


def test_torn_final_line_is_skipped(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text('{"kind": "header"}\n{"kind": "case", "rec')
    assert read_trace(path) == [{"kind": "header"}]


def test_bad_line_before_the_end_is_an_error(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text('{"kind": "header"}\nnot json\n{"kind": "end"}\n')
    with pytest.raises(ValueError, match=r"r\.jsonl.*line 2"):
        read_trace(path)


def test_trailing_blank_lines_do_not_hide_a_torn_final_line(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text('{"kind": "header"}\n{"kind": "ca\n\n')
    assert read_trace(path) == [{"kind": "header"}]
