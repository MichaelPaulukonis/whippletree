import os

from tests.fakes import FakeProvider, call, resp
from whippletree import cli


def _run_id(capsys):
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_baseline_then_report(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    assert cli.main(["run", "baseline", "--dataset", "seeded", "--runs-dir", runs]) == 0
    run_id = _run_id(capsys)
    assert cli.main(["report", run_id, "--runs-dir", runs]) == 0
    out = capsys.readouterr().out
    assert "model=baseline:random" in out
    assert "cases 2 (errored 0)" in out
    assert "stops: done 2" in out


def test_review_then_report(tmp_path, capsys, monkeypatch):
    finding = {"file": "catalog.py", "line": 18, "claim": "page 1 skips a page",
               "confidence": 0.8}
    script = [resp(calls=[call("submit_findings", {"findings": [finding]})], served_by="X")
              for _ in range(2)]
    monkeypatch.setattr(cli, "make_provider", lambda spec, routing: FakeProvider(script))
    runs = str(tmp_path / "runs")
    argv = ["run", "review", "--dataset", "seeded", "--model", "ollama:llama3.1:8b",
            "--runs-dir", runs]
    assert cli.main(argv) == 0
    run_id = _run_id(capsys)
    cli.main(["report", run_id, "--runs-dir", runs])
    out = capsys.readouterr().out
    assert "recall 0.50" in out  # found the pagination bug, not the None check
    assert "served_by=X" in out


def test_case_filter_and_limit(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    cli.main(["run", "baseline", "--dataset", "seeded", "--limit", "1", "--runs-dir", runs])
    run_id = _run_id(capsys)
    cli.main(["report", run_id, "--runs-dir", runs])
    assert "cases 1 (errored 0)" in capsys.readouterr().out


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nWT_A=from_file\nWT_B='quoted'\n")
    monkeypatch.setenv("WT_A", "from_env")
    monkeypatch.delenv("WT_B", raising=False)
    cli.load_dotenv(env)
    assert os.environ["WT_A"] == "from_env"
    assert os.environ["WT_B"] == "quoted"
