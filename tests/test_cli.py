import json
import os
from dataclasses import replace

import pytest

from tests.fakes import FakeProvider, call, resp
from whippletree import cli
from whippletree.datasets.seeded import load_seeded
from whippletree.traces import read_trace


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


# --- reproducible headers, end marker, CLI robustness ---

def _trace(tmp_path, run_id):
    return read_trace(tmp_path / "runs" / f"{run_id}.jsonl")


def _fake_review(monkeypatch, n=2):
    script = [resp(calls=[call("submit_findings", {"findings": []})]) for _ in range(n)]
    monkeypatch.setattr(cli, "make_provider", lambda spec, routing: FakeProvider(script))


REVIEW = ["run", "review", "--dataset", "seeded", "--model", "ollama:llama3.1:8b"]


def test_review_header_is_reproducible(tmp_path, capsys, monkeypatch):
    _fake_review(monkeypatch)
    argv = [*REVIEW, "--runs-dir", str(tmp_path / "runs")]
    assert cli.main(argv) == 0
    header = _trace(tmp_path, _run_id(capsys))[0]
    for key in ("git_sha", "git_dirty", "version", "argv", "case_filter", "limit",
                "dataset_hash", "prompt_sha", "window", "thresholds"):
        assert key in header, key
    assert isinstance(header["git_dirty"], bool)
    assert header["argv"] == argv
    assert header["version"] == "0.1.0"
    assert len(header["dataset_hash"]) == 64


def test_baseline_header_is_reproducible(tmp_path, capsys):
    argv = ["run", "baseline", "--dataset", "seeded", "--runs-dir", str(tmp_path / "runs")]
    assert cli.main(argv) == 0
    header = _trace(tmp_path, _run_id(capsys))[0]
    for key in ("git_sha", "git_dirty", "version", "argv", "case_filter", "limit",
                "dataset_hash", "window", "thresholds"):
        assert key in header, key
    assert "prompt_sha" not in header


def test_dataset_hash_stable_and_sensitive():
    a, b = load_seeded(), load_seeded()
    assert cli.dataset_hash(a) == cli.dataset_hash(b)
    assert cli.dataset_hash(a) == cli.dataset_hash(list(reversed(b)))
    changed = [replace(a[0], diff=a[0].diff + "+x\n"), *a[1:]]
    assert cli.dataset_hash(changed) != cli.dataset_hash(a)


def test_run_writes_end_event(tmp_path, capsys, monkeypatch):
    _fake_review(monkeypatch)
    cli.main([*REVIEW, "--runs-dir", str(tmp_path / "runs")])
    events = _trace(tmp_path, _run_id(capsys))
    assert events[-1] == {"kind": "end", "cases": 2}


def test_report_warns_on_incomplete_run(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "r1.jsonl").write_text(json.dumps(
        {"kind": "header", "run_id": "r1", "model": "m", "dataset": "seeded"}) + "\n")
    assert cli.main(["report", "r1", "--runs-dir", str(runs)]) == 0
    assert "  WARNING: incomplete run (no end event)" in capsys.readouterr().out


def test_report_complete_run_has_no_warning(tmp_path, capsys):
    runs = str(tmp_path / "runs")
    cli.main(["run", "baseline", "--dataset", "seeded", "--runs-dir", runs])
    cli.main(["report", _run_id(capsys), "--runs-dir", runs])
    assert "incomplete" not in capsys.readouterr().out


def test_unknown_run_id_is_clean_error(tmp_path, capsys):
    assert cli.main(["report", "nope", "--runs-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("whippletree: ") and "Traceback" not in err


def test_report_trace_without_header(tmp_path, capsys):
    (tmp_path / "r.jsonl").write_text(json.dumps({"kind": "end", "cases": 0}) + "\n")
    assert cli.main(["report", "r", "--runs-dir", str(tmp_path)]) == 2
    assert "header" in capsys.readouterr().err


def test_bogus_model_is_clean_error(tmp_path, capsys):
    argv = ["run", "review", "--dataset", "seeded", "--model", "bogus",
            "--runs-dir", str(tmp_path / "runs")]
    assert cli.main(argv) == 2
    assert capsys.readouterr().err.startswith("whippletree: ")
    assert not (tmp_path / "runs").exists()


def test_missing_api_key_is_clean_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # so load_dotenv can't find a .env
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    argv = ["run", "review", "--dataset", "seeded", "--model", "openrouter:x/y",
            "--runs-dir", str(tmp_path / "runs")]
    assert cli.main(argv) == 2
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


def test_empty_selection_fails_before_trace(tmp_path, capsys, monkeypatch):
    _fake_review(monkeypatch)
    runs = tmp_path / "runs"
    assert cli.main([*REVIEW, "--case", "seeded/nope", "--runs-dir", str(runs)]) == 2
    assert "no cases match" in capsys.readouterr().err
    assert not runs.exists()


@pytest.mark.parametrize("flag", ["--limit", "--repeat"])
def test_review_rejects_non_positive(flag, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([*REVIEW, flag, "0"])
    assert e.value.code == 2


@pytest.mark.parametrize("flag", ["--limit", "--k"])
def test_baseline_rejects_non_positive(flag, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["run", "baseline", "--dataset", "seeded", flag, "0"])
    assert e.value.code == 2


def test_load_dotenv_strips_export(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("export WT_EXP=yes\n")
    monkeypatch.delenv("WT_EXP", raising=False)
    cli.load_dotenv(env)
    assert os.environ["WT_EXP"] == "yes"
    monkeypatch.delenv("WT_EXP")


def test_report_labels_repeats(tmp_path, capsys, monkeypatch):
    _fake_review(monkeypatch, n=4)
    runs = str(tmp_path / "runs")
    cli.main([*REVIEW, "--repeat", "2", "--runs-dir", runs])
    cli.main(["report", _run_id(capsys), "--runs-dir", runs])
    assert "cases 2 x 2 repeats (errored 0)" in capsys.readouterr().out


def test_report_cost_sources(tmp_path, capsys, monkeypatch):
    script = [resp(calls=[call("submit_findings", {"findings": []})], cost=0.1),
              resp(calls=[call("submit_findings", {"findings": []})])]
    monkeypatch.setattr(cli, "make_provider", lambda spec, routing: FakeProvider(script))
    runs = str(tmp_path / "runs")
    cli.main([*REVIEW, "--runs-dir", runs])
    cli.main(["report", _run_id(capsys), "--runs-dir", runs])
    assert "  cost sources: free 1, provider 1" in capsys.readouterr().out
