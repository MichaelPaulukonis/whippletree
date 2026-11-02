"""Real-endpoint smoke test. Needs Ollama running with llama3.1:8b pulled.

Run: uv run pytest -m live -v
"""

import pytest

from whippletree import cli
from whippletree.traces import read_trace


@pytest.mark.live
def test_seeded_review_against_local_ollama(tmp_path, capsys):
    runs = tmp_path / "runs"
    argv = ["run", "review", "--dataset", "seeded", "--model", "ollama:llama3.1:8b",
            "--limit", "1", "--runs-dir", str(runs)]
    assert cli.main(argv) == 0
    run_id = capsys.readouterr().out.strip().splitlines()[-1]
    events = read_trace(runs / f"{run_id}.jsonl")
    cases = [e for e in events if e["kind"] == "case"]
    assert len(cases) == 1
    assert cases[0]["record"]["stop"] != "error", cases[0]["error"]
    assert any(e["kind"] == "call" for e in events)
