from pathlib import Path

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
