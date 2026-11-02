from pathlib import Path

import pytest

from whippletree.case import Range
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
    with pytest.raises(FileExistsError):
        TraceWriter(path)
    assert path.read_text() == "keep"
