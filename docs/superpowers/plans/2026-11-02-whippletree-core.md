# Whippletree Core (M1 v0, Plan 1 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working, tested, headless review harness: `whippletree run review` runs a reviewer agent over the seeded dataset through OpenRouter or Ollama, `whippletree run baseline` runs the random baseline, and `whippletree report` prints the metrics.

**Architecture:** A flat single-agent loop (`loop.py`) drives a provider (`providers/`) and per-case tools (`tools/`, bound to a `ToolEnv`). The reviewer role adds a terminal `submit_findings` tool. Scoring is a pure function over findings and ground truth. Every model call and case result is written to a JSONL trace, which `report` reads back. Internal message format is the OpenAI chat format (dicts); later native adapters translate to and from it.

**Tech Stack:** Python 3.13, uv, `openai` SDK (the only runtime dependency), stdlib `argparse`/`dataclasses`/`json`/`subprocess`, pytest, ruff, gitleaks.

**Spec:** `docs/superpowers/specs/2026-11-01-whippletree-design.md`

**Plan 2 (separate):** BugsInPy padded-diff loader (`datasets/bugsinpy.py`) and the "Done when" BugsInPy runs. Everything in Plan 1 is built so Plan 2 only adds a loader and a `--dataset bugsinpy` choice.

---

## File structure

```
pyproject.toml                       project, scripts, pytest + ruff config
.gitignore  .env.example  LICENSE  README.md
.githooks/pre-commit                 gitleaks on staged changes
.github/workflows/ci.yml             ruff + pytest (no live tests)
src/whippletree/
  __init__.py
  case.py                            Range, Padding, Case, Finding (shared domain types)
  providers/
    __init__.py
    base.py                          ToolCall, Usage, Response, errors, Provider, parse_model
    openai_compat.py                 OpenRouter + Ollama via the openai SDK
  tools/
    __init__.py
    base.py                          Tool, ToolError, Submit
    env.py                           ToolEnv
    fs.py                            read_file, list_dir, grep
  loop.py                            Limits, Counters, LoopResult, run
  roles/
    __init__.py
    reviewer.py                      prompt, submit_findings, review()
  datasets/
    __init__.py
    seeded.py                        load_seeded, tree_diff
  scoring.py                         score, CaseRecord, RunMetrics, aggregate
  pricing.py                         estimate (fallback cost)
  traces.py                          TraceWriter, read_trace, new_run_id
  baseline.py                        changed_lines, baseline_findings
  runner.py                          run_review, run_baseline, cost_for
  cli.py                             argparse entry point + report formatting
datasets/seeded/<case>/{before,after,truth.json}
tests/
  __init__.py  fakes.py
  test_*.py                          one per module
```

---

### Task 1: Project scaffold

**Files:**

- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `LICENSE`, `src/whippletree/__init__.py`, `tests/__init__.py`, `tests/test_package.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "whippletree"
version = "0.1.0"
description = "A self-built coding-agent harness that benchmarks cross-model code review."
readme = "README.md"
license = "MIT"
requires-python = ">=3.13"
dependencies = []

[project.scripts]
whippletree = "whippletree.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/whippletree"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-m 'not live'"
markers = ["live: calls a real model endpoint; run with: uv run pytest -m live"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
ignore = ["E501"]  # long lines are fine; no formatter churn
```

- [ ] **Step 2: Write `.gitignore`, `.env.example`, `LICENSE`, a stub `README.md`**

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
dist/
.env
runs/
```

`.env.example`:

```
# Copy to .env (gitignored). Never commit real keys.
OPENROUTER_API_KEY=
```

`LICENSE`: standard MIT text, `Copyright (c) 2026 Michael Paulukonis`.

`README.md`:

```markdown
# whippletree

A self-built coding-agent harness that benchmarks cross-model code review. Work in progress.
```

- [ ] **Step 3: Write the package and a first test**

`src/whippletree/__init__.py`:

```python
"""Whippletree: a self-built coding-agent harness."""

__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

`tests/test_package.py`:

```python
import whippletree


def test_version():
    assert whippletree.__version__ == "0.1.0"
```

- [ ] **Step 4: Add dependencies and run the test**

```bash
cd ~/projects/whippletree
uv add openai
uv add --dev pytest ruff
uv run pytest -v
uv run ruff check .
```

Expected: `1 passed`; ruff `All checks passed!`. `uv.lock` now pins exact versions; CI uses `uv sync --locked`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock .gitignore .env.example LICENSE README.md src tests .python-version
git commit -m "chore: scaffold uv project"
```

(`.python-version` exists only if uv created it; drop it from the command if not.)

---

### Task 2: Beads issue tracking

Follow the user's Claude-only `bd init` cleanup exactly.

- [ ] **Step 1: Init and strip the Codex integration**

```bash
cd ~/projects/whippletree
bd init --non-interactive --role maintainer
bd setup codex --remove
rm -rf .codex
bd config set export.auto false
git rm --cached .beads/issues.jsonl .beads/interactions.jsonl
printf 'issues.jsonl\ninteractions.jsonl\n' >> .beads/.gitignore
bd setup claude
```

- [ ] **Step 2: Fold the cleanup into bd's auto-commit (unpushed, so amend)**

```bash
git status --short
git add .beads AGENTS.md CLAUDE.md .agents 2>/dev/null; git add -u
git commit --amend --no-edit
git status --short
```

Expected: clean tree. Only beads/codex-related files are in the amended commit.

- [ ] **Step 3: Create follow-up beads**

```bash
bd create --title="Plan 2: BugsInPy padded-diff loader" --description="Implement datasets/bugsinpy.py per spec (padded diffs from fix applied onto B~K, zero-width deletion ranges, skip reasons, padding provenance). Then the Done-when runs: >=20 BugsInPy cases x >=2 OpenRouter models, with baseline." --type=feature --priority=1
bd create --title="Author remaining ~8 seeded cases" --description="Hand-write contamination-free seeded cases (before/after/truth.json) to reach ~10. Mix modification and deletion bugs, multi-hunk diffs. Test test_seeded_truth_points_at_bug_line guards correctness." --type=task --priority=2
bd create --title="README: public-domain whippletree photo" --description="Find a public-domain whippletree / draft-horse-team photo (Library of Congress, Wikimedia Commons), add to README with attribution." --type=task --priority=3
```

---

### Task 3: gitleaks pre-commit hook

- [ ] **Step 1: Install gitleaks**

```bash
brew install gitleaks
gitleaks version
gitleaks git --help | head -20
```

Confirm the `git` subcommand supports `--staged` and `--pre-commit`. If the installed version lacks them, use `gitleaks protect --staged --redact` in the hook instead.

Then update the wiki page `study/macos/homebrew` via the wikijs skill: package `gitleaks`, install date, why ("secret scanning pre-commit hook for whippletree; one-time scan for research-oqs"), link <https://github.com/gitleaks/gitleaks>.

- [ ] **Step 2: Write the hook**

`.githooks/pre-commit`:

```sh
#!/bin/sh
# Block commits that contain secrets.
exec gitleaks git --pre-commit --staged --redact --no-banner
```

```bash
chmod +x .githooks/pre-commit
git config core.hooksPath .githooks
```

- [ ] **Step 3: Prove the hook blocks a secret**

```bash
printf 'OPENROUTER_API_KEY=sk-or-v1-%s\n' "$(openssl rand -hex 32)" > leak.txt
git add leak.txt
git commit -m "should fail"
```

Expected: gitleaks reports a finding and the commit is refused.

```bash
git reset leak.txt && rm leak.txt
```

- [ ] **Step 4: Commit**

```bash
git add .githooks/pre-commit
git commit -m "chore: gitleaks pre-commit hook"
```

Note for anyone cloning: run `git config core.hooksPath .githooks` once (goes in README in Task 16).

---

### Task 4: Shared domain types

**Files:**

- Create: `src/whippletree/case.py`
- Test: `tests/test_case.py`

- [ ] **Step 1: Write the failing test**

`tests/test_case.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_case.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'whippletree.case'`

- [ ] **Step 3: Implement**

`src/whippletree/case.py`:

```python
"""Domain types shared across datasets, the reviewer, and scoring."""

from dataclasses import dataclass
from pathlib import Path

RANGE_KINDS = ("modification", "deletion")


@dataclass(frozen=True)
class Range:
    """Where the real bug is, in the PR head's line numbers.

    kind="deletion" means the bug was introduced by removing code (e.g. a guard
    clause). It has no lines of its own, so start == end == the line before the
    removal point.
    """

    file: str
    start: int
    end: int
    kind: str = "modification"

    def __post_init__(self):
        if self.kind not in RANGE_KINDS:
            raise ValueError(f"kind must be one of {RANGE_KINDS}, got {self.kind!r}")


@dataclass(frozen=True)
class Padding:
    """How a padded diff was built, so it can be rebuilt."""

    base: str
    commits: tuple[str, ...]
    changed_lines: int


@dataclass(frozen=True)
class Case:
    id: str
    dataset: str
    checkout_path: Path
    diff: str
    ground_truth: tuple[Range, ...]
    padding: Padding | None = None


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    claim: str
    confidence: float
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_case.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/case.py tests/test_case.py
git commit -m "feat: shared domain types"
```

---

### Task 5: Provider interface

**Files:**

- Create: `src/whippletree/providers/__init__.py` (empty), `src/whippletree/providers/base.py`
- Test: `tests/test_provider_base.py`

- [ ] **Step 1: Write the failing test**

`tests/test_provider_base.py`:

```python
import pytest

from whippletree.providers.base import Usage, parse_model


def test_parse_model_splits_on_first_colon():
    assert parse_model("ollama:llama3.1:8b") == ("ollama", "llama3.1:8b")
    assert parse_model("openrouter:google/gemini-2.5-pro") == ("openrouter", "google/gemini-2.5-pro")


@pytest.mark.parametrize("bad", ["llama3", ":x", "ollama:"])
def test_parse_model_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        parse_model(bad)


def test_usage_total():
    assert Usage(input=3, output=4, cached=2).total == 7
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_provider_base.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/providers/base.py`:

```python
"""What every provider adapter returns, whatever the wire format."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as the model sent it


@dataclass(frozen=True)
class Usage:
    input: int = 0
    output: int = 0
    cached: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output


@dataclass(frozen=True)
class Response:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str
    cost_usd: float | None = None
    served_by: str | None = None
    raw: Any = field(default=None, repr=False)


class ProviderError(Exception):
    """The call failed and retrying won't help (or retries ran out)."""


class TransientError(Exception):
    """Rate limit, server error, or network failure: worth retrying."""


class Provider(Protocol):
    def complete(
        self, messages: list[dict], tools: list[dict], model: str, settings: dict
    ) -> Response: ...


def parse_model(spec: str) -> tuple[str, str]:
    """'ollama:llama3.1:8b' -> ('ollama', 'llama3.1:8b'). Splits on the first colon."""
    provider, sep, model = spec.partition(":")
    if not sep or not provider or not model:
        raise ValueError(f"model must look like provider:model-id, got {spec!r}")
    return provider, model
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_provider_base.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/providers tests/test_provider_base.py
git commit -m "feat: provider interface"
```

---

### Task 6: OpenAI-compatible provider (OpenRouter + Ollama)

**Files:**

- Create: `src/whippletree/providers/openai_compat.py`
- Test: `tests/test_openai_compat.py`

- [ ] **Step 1: Write the failing test**

`tests/test_openai_compat.py`:

```python
from types import SimpleNamespace

import httpx2  # openai 3.x ships httpx2, not httpx
import openai
import pytest
from openai.types.chat import ChatCompletion

from whippletree.providers.base import ProviderError, ToolCall, TransientError, Usage
from whippletree.providers.openai_compat import OpenAICompatProvider, parse_response

TOOL_CALL_RESPONSE = {
    "id": "gen-1",
    "object": "chat.completion",
    "created": 1,
    "model": "google/gemini-2.5-pro",
    "provider": "Google",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 40},
        "cost": 0.0012,
    },
}

TEXT_RESPONSE = {
    "id": "x",
    "object": "chat.completion",
    "created": 1,
    "model": "llama3.1:8b",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}


def test_parse_tool_call_response():
    r = parse_response(ChatCompletion.model_validate(TOOL_CALL_RESPONSE))
    assert r.tool_calls == [ToolCall(id="call_1", name="read_file", arguments='{"path": "a.py"}')]
    assert r.usage == Usage(input=100, output=20, cached=40)
    assert r.cost_usd == 0.0012
    assert r.served_by == "Google"
    assert r.stop_reason == "tool_calls"
    assert r.text == ""


def test_parse_text_response_without_cost_or_provider():
    r = parse_response(ChatCompletion.model_validate(TEXT_RESPONSE))
    assert r.text == "hi"
    assert r.tool_calls == []
    assert r.usage == Usage(input=5, output=1, cached=0)
    assert r.cost_usd is None
    assert r.served_by is None


def test_openrouter_request_pins_routing_and_asks_for_cost():
    p = OpenAICompatProvider("openrouter", client=object(), routing=["Google"])
    req = p.build_request([{"role": "user", "content": "x"}], [], "google/gemini-2.5-pro",
                          {"temperature": 0})
    assert req["extra_body"] == {
        "usage": {"include": True},
        "provider": {"order": ["Google"], "allow_fallbacks": False},
    }
    assert req["temperature"] == 0
    assert "tools" not in req


def test_ollama_request_has_no_extra_body_but_passes_tools():
    p = OpenAICompatProvider("ollama", client=object())
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    req = p.build_request([], tools, "llama3.1:8b", {})
    assert "extra_body" not in req
    assert req["tools"] == tools


class FakeCompletions:
    def __init__(self, exc=None, resp=None):
        self.exc, self.resp, self.kwargs = exc, resp, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.resp


def _provider(completions):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatProvider("ollama", client=client)


def _status_error(cls, code):
    request = httpx2.Request("POST", "https://example.test")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.InternalServerError, 500),
        openai.APIConnectionError(request=httpx2.Request("POST", "https://example.test")),
    ],
)
def test_retryable_failures_are_transient(exc):
    with pytest.raises(TransientError):
        _provider(FakeCompletions(exc=exc)).complete([], [], "m", {})


def test_bad_request_is_permanent():
    exc = _status_error(openai.BadRequestError, 400)
    with pytest.raises(ProviderError):
        _provider(FakeCompletions(exc=exc)).complete([], [], "m", {})


def test_complete_returns_parsed_response():
    fake = FakeCompletions(resp=ChatCompletion.model_validate(TEXT_RESPONSE))
    r = _provider(fake).complete([{"role": "user", "content": "x"}], [], "llama3.1:8b", {})
    assert r.text == "hi"
    assert fake.kwargs["model"] == "llama3.1:8b"


def test_openrouter_without_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        OpenAICompatProvider("openrouter")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_openai_compat.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/providers/openai_compat.py`:

```python
"""OpenRouter and Ollama, both spoken through the openai SDK.

The SDK's own retries are off (max_retries=0) so the loop does retries and can
count them.
"""

import os

import openai

from whippletree.providers.base import ProviderError, Response, ToolCall, TransientError, Usage

# name -> (base_url, env var holding the API key; None means no key needed)
ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}


class OpenAICompatProvider:
    def __init__(self, name: str, client=None, routing: list[str] | None = None):
        if name not in ENDPOINTS:
            raise ProviderError(f"unknown provider {name!r}")
        self.name = name
        self.routing = routing
        if client is None:
            base_url, key_var = ENDPOINTS[name]
            api_key = "ollama"
            if key_var:
                api_key = os.environ.get(key_var, "")
                if not api_key:
                    raise ProviderError(f"{key_var} is not set (put it in .env)")
            client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self.client = client

    def build_request(self, messages, tools, model, settings) -> dict:
        req = {"model": model, "messages": messages, **settings}
        if tools:
            req["tools"] = tools
        if self.name == "openrouter":
            extra = {"usage": {"include": True}}
            if self.routing:
                # Pin the backend so one model id isn't silently served by different hosts.
                extra["provider"] = {"order": self.routing, "allow_fallbacks": False}
            req["extra_body"] = extra
        return req

    def complete(self, messages, tools, model, settings) -> Response:
        req = self.build_request(messages, tools, model, settings)
        try:
            raw = self.client.chat.completions.create(**req)
        except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as e:
            raise TransientError(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(str(e)) from e
            raise ProviderError(str(e)) from e
        return parse_response(raw)


def parse_response(raw) -> Response:
    choice = raw.choices[0]
    msg = choice.message
    calls = [
        ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
        for c in (msg.tool_calls or [])
        if c.type == "function"
    ]
    u = raw.usage
    usage = Usage()
    cost = None
    if u is not None:
        details = u.prompt_tokens_details
        cached = (details.cached_tokens or 0) if details else 0
        usage = Usage(input=u.prompt_tokens, output=u.completion_tokens, cached=cached)
        cost = (u.model_extra or {}).get("cost")  # OpenRouter usage accounting
    return Response(
        text=msg.content or "",
        tool_calls=calls,
        usage=usage,
        stop_reason=choice.finish_reason or "unknown",
        cost_usd=cost,
        served_by=(raw.model_extra or {}).get("provider"),  # OpenRouter: which backend served it
        raw=raw,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_openai_compat.py -v`
Expected: 10 passed. If `APIConnectionError(request=...)` construction fails on the installed SDK version, check its signature with `uv run python -c "import openai, inspect; print(inspect.signature(openai.APIConnectionError))"` and adjust the test, not the provider.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/providers/openai_compat.py tests/test_openai_compat.py
git commit -m "feat: OpenRouter + Ollama provider"
```

---

### Task 7: Tools and ToolEnv

**Files:**

- Create: `src/whippletree/tools/__init__.py` (empty), `src/whippletree/tools/base.py`, `src/whippletree/tools/env.py`, `src/whippletree/tools/fs.py`
- Test: `tests/test_fs_tools.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fs_tools.py`:

```python
import pytest

from whippletree.tools.base import ToolError
from whippletree.tools.env import ToolEnv
from whippletree.tools.fs import build_fs_tools


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("one\ntwo\nthree\nfour\n")
    (tmp_path / "b.txt").write_text("hello two\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: two\n")
    return {t.name: t for t in build_fs_tools(ToolEnv(tmp_path))}


def test_read_file_numbers_lines(tools):
    assert tools["read_file"].fn({"path": "pkg/a.py"}) == "1\tone\n2\ttwo\n3\tthree\n4\tfour"


def test_read_file_line_range(tools):
    assert tools["read_file"].fn({"path": "pkg/a.py", "start": 2, "end": 3}) == "2\ttwo\n3\tthree"


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "pkg/../../x"])
def test_paths_cannot_escape_checkout(tools, path):
    with pytest.raises(ToolError, match="escapes"):
        tools["read_file"].fn({"path": path})


def test_read_missing_file_is_tool_error(tools):
    with pytest.raises(ToolError, match="not a file"):
        tools["read_file"].fn({"path": "nope.py"})


def test_missing_required_argument_is_tool_error(tools):
    with pytest.raises(ToolError, match="path"):
        tools["read_file"].fn({})


def test_list_dir_hides_git(tools):
    assert tools["list_dir"].fn({}) == "b.txt\npkg/"


def test_grep_reports_path_and_line(tools):
    assert tools["grep"].fn({"pattern": "two"}) == "b.txt:1:hello two\npkg/a.py:2:two"


def test_grep_bad_regex_is_tool_error(tools):
    with pytest.raises(ToolError, match="regex"):
        tools["grep"].fn({"pattern": "("})


def test_tool_schema_shape(tools):
    schema = tools["read_file"].schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "read_file"
    assert schema["function"]["parameters"]["required"] == ["path"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_fs_tools.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/tools/base.py`:

```python
"""A tool is a JSON-schema'd function the model can call."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolError(Exception):
    """Bad call from the model. The message goes back to the model as the tool result."""


@dataclass(frozen=True)
class Submit:
    """Returned by a terminal tool on success: the loop stops and returns `value`."""

    value: Any


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[[dict], "str | Submit"]
    terminal: bool = False

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
```

`src/whippletree/tools/env.py`:

```python
"""Where a case's tools act. 1a: a local checkout. 1b adds a sandbox handle."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolEnv:
    checkout_path: Path
```

`src/whippletree/tools/fs.py`:

```python
"""Read-only filesystem tools, confined to the case checkout."""

import re
from pathlib import Path

from whippletree.tools.base import Tool, ToolError
from whippletree.tools.env import ToolEnv

MAX_GREP_MATCHES = 200


def resolve(env: ToolEnv, rel: str) -> Path:
    root = env.checkout_path.resolve()
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ToolError(f"path escapes the checkout: {rel}")
    return path


def _required(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(f"missing required string argument '{key}'")
    return value


def build_fs_tools(env: ToolEnv) -> list[Tool]:
    root = env.checkout_path.resolve()

    def read_file(args: dict) -> str:
        rel = _required(args, "path")
        path = resolve(env, rel)
        if not path.is_file():
            raise ToolError(f"not a file: {rel}")
        lines = path.read_text(errors="replace").splitlines()
        start = max(int(args.get("start", 1)), 1)
        end = min(int(args.get("end", len(lines))), len(lines))
        return "\n".join(f"{n}\t{lines[n - 1]}" for n in range(start, end + 1))

    def list_dir(args: dict) -> str:
        rel = args.get("path", ".")
        path = resolve(env, rel)
        if not path.is_dir():
            raise ToolError(f"not a directory: {rel}")
        names = (c.name + ("/" if c.is_dir() else "") for c in path.iterdir() if c.name != ".git")
        return "\n".join(sorted(names))

    def grep(args: dict) -> str:
        pattern = _required(args, "pattern")
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"bad regex: {e}") from e
        base = resolve(env, args.get("path", "."))
        if base.is_file():
            files = [base]
        else:
            files = sorted(f for f in base.rglob("*") if f.is_file() and ".git" not in f.parts)
        out = []
        for f in files:
            try:
                text = f.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f.relative_to(root)}:{n}:{line}")
                    if len(out) >= MAX_GREP_MATCHES:
                        return "\n".join(out) + f"\n[stopped at {MAX_GREP_MATCHES} matches]"
        return "\n".join(out) or "(no matches)"

    path_prop = {"type": "string", "description": "Path relative to the repository root."}
    return [
        Tool(
            "read_file",
            "Read a file with line numbers. Optional start/end (1-based, inclusive).",
            {
                "type": "object",
                "properties": {
                    "path": path_prop,
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                },
                "required": ["path"],
            },
            read_file,
        ),
        Tool(
            "list_dir",
            "List a directory. Defaults to the repository root.",
            {"type": "object", "properties": {"path": path_prop}},
            list_dir,
        ),
        Tool(
            "grep",
            "Search files for a Python regex. Returns path:line:text.",
            {
                "type": "object",
                "properties": {"pattern": {"type": "string"}, "path": path_prop},
                "required": ["pattern"],
            },
            grep,
        ),
    ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_fs_tools.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/tools tests/test_fs_tools.py
git commit -m "feat: read-only fs tools bound to ToolEnv"
```

---

### Task 8: The agent loop

**Files:**

- Create: `src/whippletree/loop.py`, `tests/fakes.py`
- Test: `tests/test_loop.py`

- [ ] **Step 1: Write the shared test fakes**

`tests/fakes.py`:

```python
"""Scripted stand-ins for real providers."""

import json

from whippletree.providers.base import Response, ToolCall, Usage


class FakeProvider:
    """Returns (or raises) the scripted items in order; records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def complete(self, messages, tools, model, settings):
        self.seen.append([dict(m) for m in messages])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(text="", calls=(), inp=10, out=5, cost=None, served_by=None):
    return Response(
        text=text,
        tool_calls=list(calls),
        usage=Usage(input=inp, output=out),
        stop_reason="tool_calls" if calls else "stop",
        cost_usd=cost,
        served_by=served_by,
    )


def call(name, args, id="c1"):
    return ToolCall(id=id, name=name, arguments=json.dumps(args))
```

- [ ] **Step 2: Write the failing loop tests**

`tests/test_loop.py`:

```python
import itertools

from tests.fakes import FakeProvider, call, resp
from whippletree.loop import NUDGE, Limits, run
from whippletree.providers.base import ProviderError, ToolCall, TransientError
from whippletree.tools.base import Submit, Tool, ToolError

OBJ = {"type": "object", "properties": {}}
echo = Tool("echo", "echo", OBJ, fn=lambda a: f"echo {a.get('x')}")
big = Tool("big", "big", OBJ, fn=lambda a: "x" * 50)


def _submit(args):
    if "v" not in args:
        raise ToolError("need v")
    return Submit(args["v"])


submit = Tool("submit", "submit", OBJ, fn=_submit, terminal=True)
MSGS = [{"role": "user", "content": "go"}]


def go(script, tools, limits=None, **kw):
    provider = FakeProvider(script)
    kw.setdefault("sleep", lambda s: None)
    return provider, run(provider, "m", MSGS, tools, limits=limits, **kw)


def test_without_terminal_tool_a_text_reply_is_done():
    _, r = go([resp("hi")], [echo])
    assert (r.stop, r.result) == ("done", "hi")


def test_terminal_tool_success_stops_with_its_value():
    _, r = go([resp(calls=[call("echo", {"x": 1})]), resp(calls=[call("submit", {"v": [1]})])],
              [echo, submit])
    assert (r.stop, r.result) == ("done", [1])
    assert (r.counters.steps, r.counters.tool_calls) == (2, 2)
    assert {"role": "tool", "tool_call_id": "c1", "content": "echo 1"} in r.transcript


def test_failed_terminal_call_goes_back_to_model_for_retry():
    p, r = go([resp(calls=[call("submit", {})]), resp(calls=[call("submit", {"v": 2})])], [submit])
    assert (r.stop, r.result) == ("done", 2)
    assert r.counters.tool_errors == 1
    assert r.counters.errors_by_tool == {"submit": 1}
    assert p.seen[1][-1]["content"] == "ERROR: need v"


def test_unknown_tool_and_bad_json_are_tool_errors():
    bad = resp(calls=[ToolCall("c1", "nope", "{}"), ToolCall("c2", "echo", "{not json")])
    _, r = go([bad, resp(calls=[call("submit", {"v": 0})])], [echo, submit])
    assert r.stop == "done"
    assert r.counters.tool_errors == 2
    tool_msgs = [m for m in r.transcript if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("ERROR: unknown tool")
    assert tool_msgs[1]["content"].startswith("ERROR: arguments are not valid JSON")


def test_no_tool_calls_nudges_once_then_no_submit():
    p, r = go([resp("done?"), resp("really done")], [echo, submit])
    assert r.stop == "no_submit"
    assert r.result is None
    assert r.counters.nudges == 1
    assert p.seen[1][-1] == {"role": "user", "content": NUDGE}


def test_nudge_then_submit_is_done():
    _, r = go([resp("done?"), resp(calls=[call("submit", {"v": "ok"})])], [submit])
    assert (r.stop, r.result, r.counters.nudges) == ("done", "ok", 1)


def test_max_steps():
    script = [resp(calls=[call("echo", {})]) for _ in range(3)]
    _, r = go(script, [echo, submit], Limits(max_steps=2))
    assert (r.stop, r.counters.steps) == ("max_steps", 2)


def test_token_budget():
    script = [resp(calls=[call("echo", {})]) for _ in range(3)]  # 15 tokens each
    _, r = go(script, [echo, submit], Limits(token_budget=25))
    assert (r.stop, r.counters.steps) == ("budget", 2)


def test_budget_never_discards_a_submission():
    _, r = go([resp(calls=[call("submit", {"v": 1})])], [submit], Limits(token_budget=5))
    assert (r.stop, r.result) == ("done", 1)


def test_wall_clock_timeout():
    clock = itertools.count(0, 200).__next__  # each clock() call advances 200s
    _, r = go([resp(calls=[call("echo", {})])], [echo, submit], Limits(wall_clock_s=300),
              clock=clock)
    assert (r.stop, r.counters.steps) == ("timeout", 1)


def test_transient_errors_are_retried_with_backoff():
    sleeps = []
    _, r = go([TransientError("429"), TransientError("503"), resp("ok")], [echo],
              sleep=sleeps.append)
    assert (r.stop, r.result) == ("done", "ok")
    assert r.counters.retries == 2
    assert sleeps == [1, 2]


def test_retries_exhausted_is_error():
    _, r = go([TransientError("429"), TransientError("429")], [echo], Limits(max_retries=1))
    assert r.stop == "error"
    assert "gave up" in r.error


def test_permanent_error_is_not_retried():
    _, r = go([ProviderError("400 bad request")], [echo])
    assert (r.stop, r.counters.retries) == ("error", 0)


def test_tool_output_is_truncated():
    _, r = go([resp(calls=[call("big", {})]), resp(calls=[call("submit", {"v": 1})])],
              [big, submit], Limits(max_tool_output_bytes=10))
    content = next(m["content"] for m in r.transcript if m["role"] == "tool")
    assert content == "x" * 10 + "\n[truncated 40 bytes]"
    assert r.counters.truncated_bytes == 40


def test_tokens_and_reported_cost_are_counted():
    script = [resp(calls=[call("echo", {})], cost=0.01), resp(calls=[call("submit", {"v": 1})],
                                                              cost=0.01)]
    _, r = go(script, [echo, submit])
    c = r.counters
    assert (c.input_tokens, c.output_tokens) == (20, 10)
    assert round(c.cost_usd, 6) == 0.02
    assert c.cost_reported_calls == 2


def test_on_call_gets_one_event_per_model_call():
    events = []
    go([resp(calls=[call("echo", {})], served_by="Google"), resp(calls=[call("submit", {"v": 1})])],
       [echo, submit], on_call=events.append)
    assert [e["step"] for e in events] == [1, 2]
    assert events[0]["served_by"] == "Google"
    assert events[0]["tool_calls"] == ["echo"]
    assert events[0]["usage"] == {"input": 10, "output": 5, "cached": 0}


def test_every_tool_call_gets_a_result_even_after_submit():
    both = resp(calls=[call("submit", {"v": 1}, id="a"), call("echo", {}, id="b")])
    _, r = go([both], [echo, submit])
    assert r.stop == "done"
    assert [m["tool_call_id"] for m in r.transcript if m["role"] == "tool"] == ["a", "b"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_loop.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'whippletree.loop'`.

- [ ] **Step 4: Implement**

`src/whippletree/loop.py`:

```python
"""The agent loop: call the model, run the tools it asks for, repeat.

Flat and single-agent. It knows nothing about roles, datasets, or where tools
execute. Messages use the OpenAI chat format.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from whippletree.providers.base import Provider, ProviderError, Response, TransientError
from whippletree.tools.base import Submit, Tool, ToolError

NUDGE = "You have not submitted. Call submit_findings to complete your review."

_NOTHING = object()


@dataclass(frozen=True)
class Limits:
    max_steps: int = 20
    token_budget: int = 200_000
    wall_clock_s: float = 300.0
    max_tool_output_bytes: int = 20_000
    max_retries: int = 3


@dataclass
class Counters:
    steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    errors_by_tool: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    truncated_bytes: int = 0
    nudges: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cost_reported_calls: int = 0


@dataclass
class LoopResult:
    result: Any
    transcript: list[dict]
    stop: str  # done | no_submit | max_steps | budget | timeout | error
    counters: Counters
    error: str | None = None


def run(
    provider: Provider,
    model: str,
    messages: list[dict],
    tools: list[Tool],
    limits: Limits | None = None,
    settings: dict | None = None,
    nudge: str | None = NUDGE,
    on_call: Callable[[dict], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> LoopResult:
    limits = limits or Limits()
    transcript = list(messages)
    by_name = {t.name: t for t in tools}
    schemas = [t.schema() for t in tools]
    has_terminal = any(t.terminal for t in tools)
    c = Counters()
    started = clock()

    def finish(stop, result=None, error=None):
        return LoopResult(result, transcript, stop, c, error)

    while True:
        if c.steps >= limits.max_steps:
            return finish("max_steps")
        if clock() - started > limits.wall_clock_s:
            return finish("timeout")

        t0 = clock()
        try:
            resp = _call_with_retry(provider, transcript, schemas, model, settings or {}, limits,
                                    c, sleep)
        except ProviderError as e:
            return finish("error", error=str(e))
        latency = clock() - t0
        _account(c, resp)
        if on_call:
            on_call({
                "step": c.steps,
                "latency_s": round(latency, 3),
                "usage": asdict(resp.usage),
                "cost_usd": resp.cost_usd,
                "served_by": resp.served_by,
                "stop_reason": resp.stop_reason,
                "tool_calls": [tc.name for tc in resp.tool_calls],
            })
        transcript.append(_assistant_message(resp))
        over_budget = c.input_tokens + c.output_tokens > limits.token_budget

        if not resp.tool_calls:
            if not has_terminal:
                return finish("done", result=resp.text)
            if over_budget:
                return finish("budget")
            if nudge and c.nudges < 1:
                c.nudges += 1
                transcript.append({"role": "user", "content": nudge})
                continue
            return finish("no_submit")

        # Every tool call must get a result message, even after a successful submit.
        submitted = _NOTHING
        for tc in resp.tool_calls:
            c.tool_calls += 1
            output, value = _dispatch(by_name, tc, c)
            transcript.append(
                {"role": "tool", "tool_call_id": tc.id, "content": _truncate(output, limits, c)}
            )
            if value is not _NOTHING and submitted is _NOTHING:
                submitted = value
        if submitted is not _NOTHING:
            return finish("done", result=submitted)
        if over_budget:
            return finish("budget")


def _call_with_retry(provider, transcript, schemas, model, settings, limits, c, sleep) -> Response:
    for attempt in range(limits.max_retries + 1):
        try:
            return provider.complete(transcript, schemas, model, settings)
        except TransientError as e:
            if attempt == limits.max_retries:
                raise ProviderError(f"gave up after {attempt} retries: {e}") from e
            c.retries += 1
            sleep(2**attempt)
    raise AssertionError("unreachable")


def _account(c: Counters, resp: Response) -> None:
    c.steps += 1
    c.input_tokens += resp.usage.input
    c.output_tokens += resp.usage.output
    c.cached_tokens += resp.usage.cached
    if resp.cost_usd is not None:
        c.cost_usd += resp.cost_usd
        c.cost_reported_calls += 1


def _assistant_message(resp: Response) -> dict:
    if not resp.tool_calls:
        return {"role": "assistant", "content": resp.text}
    return {
        "role": "assistant",
        "content": resp.text or None,
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in resp.tool_calls
        ],
    }


def _dispatch(by_name: dict, tc, c: Counters):
    tool = by_name.get(tc.name)
    try:
        if tool is None:
            raise ToolError(f"unknown tool: {tc.name}")
        try:
            args = json.loads(tc.arguments or "{}")
        except json.JSONDecodeError as e:
            raise ToolError(f"arguments are not valid JSON: {e}") from e
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        out = tool.fn(args)
    except ToolError as e:
        c.tool_errors += 1
        c.errors_by_tool[tc.name] = c.errors_by_tool.get(tc.name, 0) + 1
        return f"ERROR: {e}", _NOTHING
    if isinstance(out, Submit):
        return "submitted", out.value
    return out, _NOTHING


def _truncate(text: str, limits: Limits, c: Counters) -> str:
    data = text.encode()
    if len(data) <= limits.max_tool_output_bytes:
        return text
    cut = len(data) - limits.max_tool_output_bytes
    c.truncated_bytes += cut
    kept = data[: limits.max_tool_output_bytes].decode(errors="ignore")
    return f"{kept}\n[truncated {cut} bytes]"
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_loop.py -v`
Expected: 17 passed.

- [ ] **Step 6: Commit**

```bash
git add src/whippletree/loop.py tests/fakes.py tests/test_loop.py
git commit -m "feat: agent loop with terminal tools, limits, retries"
```

---

### Task 9: Reviewer role

**Files:**

- Create: `src/whippletree/roles/__init__.py` (empty), `src/whippletree/roles/reviewer.py`
- Test: `tests/test_reviewer.py`

- [ ] **Step 1: Write the failing test**

`tests/test_reviewer.py`:

```python
import pytest

from tests.fakes import FakeProvider, call, resp
from whippletree.case import Case, Finding
from whippletree.roles.reviewer import make_submit_tool, review, validate_findings
from whippletree.tools.base import Submit, ToolError

GOOD = {"file": "a.py", "line": 3, "claim": "off by one", "confidence": 0.9}


def test_valid_findings():
    assert validate_findings({"findings": [GOOD]}) == [Finding("a.py", 3, "off by one", 0.9)]


def test_empty_list_is_valid():
    assert validate_findings({"findings": []}) == []


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_reviewer.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/roles/reviewer.py`:

```python
"""The reviewer role: a prompt, read-only tools, and a terminal submit_findings tool."""

from collections.abc import Callable
from dataclasses import dataclass

from whippletree.case import Case, Finding
from whippletree.loop import Limits, LoopResult, run
from whippletree.providers.base import Provider
from whippletree.tools.base import Submit, Tool, ToolError
from whippletree.tools.env import ToolEnv
from whippletree.tools.fs import build_fs_tools

SYSTEM_PROMPT = """You are reviewing a pull request for bugs.

You get the PR's diff. Use read_file, list_dir and grep to read the surrounding code
in the repository at the PR's head; line numbers refer to that version.

Report real defects only (code that behaves wrongly), not style or naming.
When you are done, call submit_findings exactly once with every bug you found
(an empty list if you found none). For each finding give:
- file: path relative to the repository root
- line: line number in the PR's head version
- claim: one sentence saying what is wrong
- confidence: a number from 0 to 1"""

SUBMIT_PARAMETERS = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "Path relative to the repo root."},
                    "line": {"type": "integer", "description": "Line in the PR's head version."},
                    "claim": {"type": "string", "description": "One sentence: what is wrong."},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["file", "line", "claim", "confidence"],
            },
        }
    },
    "required": ["findings"],
}

KEYS = ("file", "line", "claim", "confidence")


def validate_findings(args: dict) -> list[Finding]:
    """Check shape and types only. Never checks that files or lines exist: that would leak hints."""
    raw = args.get("findings")
    if not isinstance(raw, list):
        raise ToolError("'findings' must be a list (use [] if you found nothing)")
    out = []
    for i, f in enumerate(raw):
        if not isinstance(f, dict):
            raise ToolError(f"finding {i} must be an object")
        missing = [k for k in KEYS if k not in f]
        if missing:
            raise ToolError(f"finding {i} is missing: {', '.join(missing)}")
        file, line, claim, conf = (f[k] for k in KEYS)
        if not isinstance(file, str) or not file:
            raise ToolError(f"finding {i}: 'file' must be a non-empty string")
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ToolError(f"finding {i}: 'line' must be an integer >= 1")
        if not isinstance(claim, str) or not claim:
            raise ToolError(f"finding {i}: 'claim' must be a non-empty string")
        if isinstance(conf, bool) or not isinstance(conf, int | float) or not 0 <= conf <= 1:
            raise ToolError(f"finding {i}: 'confidence' must be a number from 0 to 1")
        out.append(Finding(file=file, line=line, claim=claim, confidence=float(conf)))
    return out


def make_submit_tool() -> Tool:
    return Tool(
        "submit_findings",
        "Submit your review. Call exactly once, when done.",
        SUBMIT_PARAMETERS,
        fn=lambda args: Submit(validate_findings(args)),
        terminal=True,
    )


def build_user_message(case: Case) -> str:
    return f"Review this pull request.\n\n```diff\n{case.diff}\n```"


@dataclass
class ReviewResult:
    findings: list[Finding]
    loop: LoopResult

    @property
    def parse_failures(self) -> int:
        return self.loop.counters.errors_by_tool.get("submit_findings", 0)


def review(
    case: Case,
    provider: Provider,
    model: str,
    limits: Limits | None = None,
    settings: dict | None = None,
    on_call: Callable[[dict], None] | None = None,
) -> ReviewResult:
    tools = build_fs_tools(ToolEnv(case.checkout_path)) + [make_submit_tool()]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(case)},
    ]
    result = run(provider, model, messages, tools, limits=limits, settings=settings,
                 on_call=on_call)
    findings = result.result if result.stop == "done" else []
    return ReviewResult(findings=findings, loop=result)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_reviewer.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/roles tests/test_reviewer.py
git commit -m "feat: reviewer role with submit_findings"
```

---

### Task 10: Seeded dataset (loader + first 2 cases)

Cases are stored as `before/` and `after/` trees; the loader builds the diff with `git diff --no-index`, so nobody hand-writes patch files. The checkout is `after/` (the PR head).

**Files:**

- Create: `src/whippletree/datasets/__init__.py` (empty), `src/whippletree/datasets/seeded.py`
- Create: `datasets/seeded/pagination-off-by-one/{before/catalog.py,after/catalog.py,truth.json}`
- Create: `datasets/seeded/missing-none-check/{before/config.py,after/config.py,truth.json}`
- Test: `tests/test_seeded.py`

- [ ] **Step 1: Write case 1, a modification bug**

`datasets/seeded/pagination-off-by-one/before/catalog.py`:

```python
"""Product catalog helpers."""

from dataclasses import dataclass


@dataclass
class Product:
    sku: str
    name: str
    price_cents: int


def page(items, page_number, page_size):
    start = (page_number - 1) * page_size
    return items[start:start + page_size]


def total_cents(items):
    total = 0
    for item in items:
        total += item.price_cents
    return total
```

`datasets/seeded/pagination-off-by-one/after/catalog.py` (the bug: line 18 drops the `- 1`, so page 1 skips the first page):

```python
"""Product catalog helpers."""

from dataclasses import dataclass


@dataclass
class Product:
    sku: str
    name: str
    price_cents: int
    in_stock: bool = True


def page(items, page_number, page_size):
    """Return one 1-indexed page of items."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    start = page_number * page_size
    return items[start:start + page_size]


def total_cents(items):
    return sum(item.price_cents for item in items)


def in_stock(items):
    return [item for item in items if item.in_stock]


def search(items, text):
    needle = text.lower()
    return [item for item in items if needle in item.name.lower()]
```

`datasets/seeded/pagination-off-by-one/truth.json`:

```json
{
  "ranges": [
    {"file": "catalog.py", "start": 18, "end": 18, "kind": "modification",
     "expect": "start = page_number * page_size"}
  ]
}
```

- [ ] **Step 2: Write case 2, a deletion bug**

`datasets/seeded/missing-none-check/before/config.py`:

```python
"""Load settings from a dict-like source."""


def get_port(settings, default=8080):
    value = settings.get("port")
    if value is None:
        return default
    return int(value)


def get_host(settings):
    return settings.get("host", "localhost")
```

`datasets/seeded/missing-none-check/after/config.py` (the bug: the `None` guard is gone, so a missing port crashes `int(None)`; removal point is after line 7):

```python
"""Load settings from a dict-like source."""

import os


def get_port(settings, default=8080):
    value = settings.get("port")
    return int(value)


def get_host(settings):
    return settings.get("host", "localhost")


def get_debug(settings):
    raw = os.environ.get("APP_DEBUG", settings.get("debug", "false"))
    return str(raw).lower() in ("1", "true", "yes")
```

`datasets/seeded/missing-none-check/truth.json`:

```json
{
  "ranges": [
    {"file": "config.py", "start": 7, "end": 7, "kind": "deletion",
     "expect": "value = settings.get(\"port\")"}
  ]
}
```

- [ ] **Step 3: Write the failing test**

`tests/test_seeded.py`:

```python
import json

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
```

- [ ] **Step 4: Run to verify it fails**

Run: `uv run pytest tests/test_seeded.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 5: Implement**

`src/whippletree/datasets/seeded.py`:

```python
"""Hand-seeded cases: datasets/seeded/<id>/{before/, after/, truth.json}."""

import json
import subprocess
from pathlib import Path

from whippletree.case import Case, Range

SEEDED_ROOT = Path(__file__).resolve().parents[3] / "datasets" / "seeded"


def load_seeded(root: Path = SEEDED_ROOT) -> list[Case]:
    cases = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        truth = json.loads((case_dir / "truth.json").read_text())
        ranges = tuple(
            Range(r["file"], r["start"], r["end"], r.get("kind", "modification"))
            for r in truth["ranges"]
        )
        cases.append(
            Case(
                id=f"seeded/{case_dir.name}",
                dataset="seeded",
                checkout_path=case_dir / "after",
                diff=tree_diff(case_dir / "before", case_dir / "after"),
                ground_truth=ranges,
            )
        )
    return cases


def tree_diff(before: Path, after: Path) -> str:
    """Unified diff of two trees, with a/ and b/ paths relative to each tree."""
    proc = subprocess.run(
        ["git", "diff", "--no-index", "--no-color", before.name, after.name],
        cwd=before.parent,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):  # 1 just means "there are differences"
        raise RuntimeError(f"git diff failed: {proc.stderr}")
    return proc.stdout.replace(f"a/{before.name}/", "a/").replace(f"b/{after.name}/", "b/")
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_seeded.py -v`
Expected: 6 passed. If `test_seeded_truth_points_at_bug_line` fails, the case files don't match the line numbers in `truth.json`: fix the case, not the test.

- [ ] **Step 7: Commit**

```bash
git add src/whippletree/datasets datasets tests/test_seeded.py
git commit -m "feat: seeded dataset loader and first two cases"
```

---

### Task 11: Scoring

**Files:**

- Create: `src/whippletree/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scoring.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_scoring.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/scoring.py`:

```python
"""Score findings against ground truth. Pure functions, no I/O."""

from collections import defaultdict
from dataclasses import dataclass

from whippletree.case import Finding, Range

DEFAULT_WINDOW = 5
DEFAULT_THRESHOLDS = (0.0, 0.5, 0.7, 0.9)


@dataclass(frozen=True)
class CaseScore:
    tp: int  # ground-truth ranges hit
    fp: int  # findings that hit nothing
    dupes: int  # extra findings on an already-hit range
    hit: tuple[bool, ...]  # per range

    @property
    def found(self) -> bool:
        """All ranges in a case are one bug: found if any range was hit."""
        return any(self.hit)


def same_file(found: str, truth: str) -> bool:
    name = found.removeprefix("./")
    return name in (truth, f"a/{truth}", f"b/{truth}")


def score(findings, truth: tuple[Range, ...], window: int = DEFAULT_WINDOW) -> CaseScore:
    hit = [False] * len(truth)
    tp = fp = dupes = 0
    for finding in findings:
        idx = next(
            (i for i, r in enumerate(truth)
             if same_file(finding.file, r.file) and r.start - window <= finding.line <= r.end + window),
            None,
        )
        if idx is None:
            fp += 1
        elif hit[idx]:
            dupes += 1
        else:
            hit[idx] = True
            tp += 1
    return CaseScore(tp, fp, dupes, tuple(hit))


@dataclass(frozen=True)
class CaseRecord:
    """One reviewed case, as written to the trace and read back by report."""

    case_id: str
    repeat: int
    findings: tuple[Finding, ...]
    truth: tuple[Range, ...]
    stop: str
    tokens: int
    cost_usd: float | None
    cost_source: str
    tool_errors: int
    parse_failures: int
    errored: bool

    @classmethod
    def from_dict(cls, d: dict) -> "CaseRecord":
        return cls(
            case_id=d["case_id"],
            repeat=d["repeat"],
            findings=tuple(Finding(**x) for x in d["findings"]),
            truth=tuple(Range(**x) for x in d["truth"]),
            stop=d["stop"],
            tokens=d["tokens"],
            cost_usd=d["cost_usd"],
            cost_source=d["cost_source"],
            tool_errors=d["tool_errors"],
            parse_failures=d["parse_failures"],
            errored=d["errored"],
        )


@dataclass(frozen=True)
class RunMetrics:
    cases: int
    errored: int
    recall: float  # share of cases whose bug was found
    precision: float  # share of findings that hit a bug (dupes count as hits)
    f1: float
    cost_usd: float | None
    cost_per_tp: float | None
    tokens_per_tp: float | None
    tool_errors: int
    parse_failures: int
    recall_by_kind: dict[str, float]
    pr_curve: list[tuple[float, float, float]]  # (threshold, precision, recall)


def case_kind(truth: tuple[Range, ...]) -> str:
    kinds = {r.kind for r in truth}
    if not kinds:
        return "none"
    return kinds.pop() if len(kinds) == 1 else "mixed"


def aggregate(records, window: int = DEFAULT_WINDOW,
              thresholds=DEFAULT_THRESHOLDS) -> RunMetrics:
    ok = [r for r in records if not r.errored]

    def at(threshold: float) -> tuple[float, float, int]:
        hits = fps = found = 0
        for r in ok:
            s = score([x for x in r.findings if x.confidence >= threshold], r.truth, window)
            hits += s.tp + s.dupes
            fps += s.fp
            found += s.found
        precision = hits / (hits + fps) if hits + fps else 0.0
        recall = found / len(ok) if ok else 0.0
        return precision, recall, found

    precision, recall, found = at(0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    costs = [r.cost_usd for r in records]
    cost = None if any(c is None for c in costs) else sum(costs)
    tokens = sum(r.tokens for r in records)

    by_kind: dict[str, list[bool]] = defaultdict(list)
    for r in ok:
        by_kind[case_kind(r.truth)].append(score(r.findings, r.truth, window).found)

    return RunMetrics(
        cases=len(ok),
        errored=len(records) - len(ok),
        recall=recall,
        precision=precision,
        f1=f1,
        cost_usd=cost,
        cost_per_tp=cost / found if cost is not None and found else None,
        tokens_per_tp=tokens / found if found else None,
        tool_errors=sum(r.tool_errors for r in records),
        parse_failures=sum(r.parse_failures for r in records),
        recall_by_kind={k: sum(v) / len(v) for k, v in by_kind.items()},
        pr_curve=[(t, *at(t)[:2]) for t in thresholds],
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_scoring.py -v`
Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/scoring.py tests/test_scoring.py
git commit -m "feat: scoring and run metrics"
```

---

### Task 12: Pricing fallback and traces

**Files:**

- Create: `src/whippletree/pricing.py`, `src/whippletree/traces.py`
- Test: `tests/test_pricing.py`, `tests/test_traces.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_pricing.py`:

```python
from whippletree import pricing


def test_local_models_are_free():
    assert pricing.estimate("ollama:llama3.1:8b", 1000, 1000) == 0.0


def test_unknown_model_is_none():
    assert pricing.estimate("openrouter:some/model", 1000, 1000) is None


def test_table_entry_is_used(monkeypatch):
    monkeypatch.setitem(pricing.PRICES, "openrouter:x/y", (2.0, 10.0))
    assert pricing.estimate("openrouter:x/y", 1_000_000, 100_000) == 3.0
```

`tests/test_traces.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_pricing.py tests/test_traces.py -v`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement**

`src/whippletree/pricing.py`:

```python
"""Fallback cost when the provider doesn't report one. OpenRouter reports its own."""

from whippletree.providers.base import parse_model

# "provider:model" -> (USD per million input tokens, USD per million output tokens).
# Add an entry when benchmarking a model whose provider doesn't report cost.
PRICES: dict[str, tuple[float, float]] = {}

FREE_PROVIDERS = {"ollama"}


def estimate(model_spec: str, input_tokens: int, output_tokens: int) -> float | None:
    provider, _ = parse_model(model_spec)
    if provider in FREE_PROVIDERS:
        return 0.0
    price = PRICES.get(model_spec)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
```

`src/whippletree/traces.py`:

```python
"""Append-only JSONL run traces: one header, then call and case events."""

import json
import secrets
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)


def _default(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


class TraceWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("w")

    def write(self, kind: str, **data) -> None:
        self._file.write(json.dumps({"kind": kind, **data}, default=_default) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_pricing.py tests/test_traces.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/pricing.py src/whippletree/traces.py tests/test_pricing.py tests/test_traces.py
git commit -m "feat: pricing fallback and JSONL traces"
```

---

### Task 13: Random baseline

**Files:**

- Create: `src/whippletree/baseline.py`
- Test: `tests/test_baseline.py`

- [ ] **Step 1: Write the failing test**

`tests/test_baseline.py`:

```python
import random
from pathlib import Path

from whippletree.baseline import baseline_findings, changed_lines
from whippletree.case import Case

DIFF = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1,3 +1,4 @@
 a
-b
+B
+C
 d
@@ -10,2 +11,1 @@
 j
-k
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-bye
"""


def test_changed_lines_use_head_line_numbers():
    # -b at head line 2 -> deletion point 1; +B -> 2; +C -> 3; -k after j(11) -> 11
    assert changed_lines(DIFF) == [("x.py", 1), ("x.py", 2), ("x.py", 3), ("x.py", 11)]


def _case():
    return Case(id="c", dataset="t", checkout_path=Path("."), diff=DIFF, ground_truth=())


def test_baseline_is_deterministic_for_a_seed():
    a = baseline_findings(_case(), 2, random.Random(0))
    b = baseline_findings(_case(), 2, random.Random(0))
    assert a == b and len(a) == 2
    assert all(f.claim == "baseline guess" for f in a)


def test_baseline_caps_at_available_lines():
    assert len(baseline_findings(_case(), 99, random.Random(0))) == 4
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_baseline.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/baseline.py`:

```python
"""A reviewer that guesses: random changed lines. Sets the floor models must beat."""

import random
import re

from whippletree.case import Case, Finding

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def changed_lines(diff: str) -> list[tuple[str, int]]:
    """(file, head line) for every added line, plus the line before each removal point."""
    out = set()
    file, line = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            file = None if path == "/dev/null" else path.removeprefix("b/")
            continue
        if raw.startswith("--- "):
            continue
        m = _HUNK.match(raw)
        if m:
            line = int(m.group(1))
            continue
        if file is None:
            continue
        if raw.startswith("+"):
            out.add((file, line))
            line += 1
        elif raw.startswith("-"):
            out.add((file, max(line - 1, 1)))
        elif raw.startswith(" "):
            line += 1
    return sorted(out)


def baseline_findings(case: Case, k: int, rng: random.Random) -> list[Finding]:
    lines = changed_lines(case.diff)
    picks = rng.sample(lines, min(k, len(lines)))
    return [Finding(file, line, "baseline guess", 0.5) for file, line in sorted(picks)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_baseline.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/baseline.py tests/test_baseline.py
git commit -m "feat: random-line baseline"
```

---

### Task 14: Runner

**Files:**

- Create: `src/whippletree/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test**

`tests/test_runner.py`:

```python
import random

import pytest

from tests.fakes import FakeProvider, call, resp
from whippletree.case import Case, Range
from whippletree.loop import Counters
from whippletree.runner import cost_for, run_baseline, run_review
from whippletree.traces import TraceWriter, read_trace

FINDING = {"file": "a.py", "line": 1, "claim": "bug", "confidence": 0.9}


@pytest.fixture
def case(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    return Case(id="t/1", dataset="t", checkout_path=tmp_path,
                diff="--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n",
                ground_truth=(Range("a.py", 1, 1),))


def test_run_review_writes_calls_and_cases(case, tmp_path):
    provider = FakeProvider([
        resp(calls=[call("submit_findings", {"findings": [FINDING]})], cost=0.002),
        resp(calls=[call("submit_findings", {"findings": []})], cost=0.002),
    ])
    path = tmp_path / "run.jsonl"
    with TraceWriter(path) as trace:
        records = run_review([case], "openrouter:x/y", provider, trace, repeat=2)
    assert [r.repeat for r in records] == [0, 1]
    assert records[0].findings[0].line == 1
    assert (records[0].cost_usd, records[0].cost_source) == (0.002, "provider")
    kinds = [e["kind"] for e in read_trace(path)]
    assert kinds == ["call", "case", "call", "case"]


def test_run_baseline_records(case, tmp_path):
    with TraceWriter(tmp_path / "b.jsonl") as trace:
        records = run_baseline([case], 3, random.Random(0), trace)
    assert records[0].cost_usd == 0.0
    assert records[0].findings  # guessed at least one changed line


def test_cost_for_prefers_provider_cost():
    c = Counters(steps=2, cost_usd=0.5, cost_reported_calls=2)
    assert cost_for("openrouter:x/y", c) == (0.5, "provider")


def test_cost_for_falls_back_to_table():
    c = Counters(steps=1, input_tokens=100, output_tokens=10)
    assert cost_for("ollama:llama3.1:8b", c) == (0.0, "table")
    assert cost_for("openrouter:x/y", c) == (None, "unknown")


def test_cost_for_no_calls_is_free():
    assert cost_for("openrouter:x/y", Counters()) == (0.0, "none")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/whippletree/runner.py`:

```python
"""Run a reviewer (or the baseline) over cases, writing the trace as it goes."""

import random

from whippletree.baseline import baseline_findings
from whippletree.case import Case
from whippletree.loop import Counters, Limits
from whippletree.pricing import estimate
from whippletree.providers.base import Provider, parse_model
from whippletree.roles.reviewer import review
from whippletree.scoring import CaseRecord
from whippletree.traces import TraceWriter


def cost_for(model_spec: str, c: Counters) -> tuple[float | None, str]:
    if c.steps == 0:
        return 0.0, "none"
    if c.cost_reported_calls == c.steps:
        return c.cost_usd, "provider"
    est = estimate(model_spec, c.input_tokens, c.output_tokens)
    return (est, "table") if est is not None else (None, "unknown")


def run_review(
    cases: list[Case],
    model_spec: str,
    provider: Provider,
    trace: TraceWriter,
    limits: Limits | None = None,
    settings: dict | None = None,
    repeat: int = 1,
) -> list[CaseRecord]:
    _, model = parse_model(model_spec)
    records = []
    for rep in range(repeat):
        for case in cases:
            def on_call(event, case_id=case.id, rep=rep):
                trace.write("call", case_id=case_id, repeat=rep, **event)

            result = review(case, provider, model, limits=limits, settings=settings,
                            on_call=on_call)
            c = result.loop.counters
            cost, source = cost_for(model_spec, c)
            record = CaseRecord(
                case_id=case.id,
                repeat=rep,
                findings=tuple(result.findings),
                truth=case.ground_truth,
                stop=result.loop.stop,
                tokens=c.input_tokens + c.output_tokens,
                cost_usd=cost,
                cost_source=source,
                tool_errors=c.tool_errors,
                parse_failures=result.parse_failures,
                errored=result.loop.stop == "error",
            )
            trace.write("case", record=record, counters=c, padding=case.padding,
                        error=result.loop.error)
            records.append(record)
    return records


def run_baseline(cases: list[Case], k: int, rng: random.Random,
                 trace: TraceWriter) -> list[CaseRecord]:
    records = []
    for case in cases:
        record = CaseRecord(
            case_id=case.id,
            repeat=0,
            findings=tuple(baseline_findings(case, k, rng)),
            truth=case.ground_truth,
            stop="done",
            tokens=0,
            cost_usd=0.0,
            cost_source="none",
            tool_errors=0,
            parse_failures=0,
            errored=False,
        )
        trace.write("case", record=record, padding=case.padding)
        records.append(record)
    return records
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/whippletree/runner.py tests/test_runner.py
git commit -m "feat: review and baseline runners"
```

---

### Task 15: CLI and report

**Files:**

- Create: `src/whippletree/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `ImportError`.

- [ ] **Step 3: Implement**

`src/whippletree/cli.py`:

```python
"""whippletree run review|baseline, whippletree report."""

import argparse
import os
import random
import subprocess
from pathlib import Path

from whippletree.datasets.seeded import load_seeded
from whippletree.loop import Limits
from whippletree.providers.base import parse_model
from whippletree.providers.openai_compat import OpenAICompatProvider
from whippletree.runner import run_baseline, run_review
from whippletree.scoring import CaseRecord, RunMetrics, aggregate
from whippletree.traces import TraceWriter, new_run_id, read_trace

DATASETS = ("seeded",)
SETTINGS = {"temperature": 0}


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader. Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def make_provider(model_spec: str, routing: list[str] | None):
    name, _ = parse_model(model_spec)
    return OpenAICompatProvider(name, routing=routing)


def git_sha() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True)
        return proc.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_cases(dataset: str, case_id: str | None, limit: int | None):
    cases = load_seeded() if dataset == "seeded" else []
    if case_id:
        cases = [c for c in cases if c.id == case_id]
    return cases[:limit] if limit else cases


def _trace_path(runs_dir: str, run_id: str) -> Path:
    return Path(runs_dir) / f"{run_id}.jsonl"


def cmd_review(args) -> int:
    cases = load_cases(args.dataset, args.case, args.limit)
    routing = args.routing.split(",") if args.routing else None
    provider = make_provider(args.model, routing)
    limits = Limits()
    run_id = new_run_id()
    with TraceWriter(_trace_path(args.runs_dir, run_id)) as trace:
        trace.write("header", run_id=run_id, mode="review", model=args.model,
                    dataset=args.dataset, git_sha=git_sha(), limits=limits, settings=SETTINGS,
                    routing=routing, repeat=args.repeat)
        run_review(cases, args.model, provider, trace, limits=limits, settings=SETTINGS,
                   repeat=args.repeat)
    print(run_id)
    return 0


def cmd_baseline(args) -> int:
    cases = load_cases(args.dataset, None, args.limit)
    run_id = new_run_id()
    with TraceWriter(_trace_path(args.runs_dir, run_id)) as trace:
        trace.write("header", run_id=run_id, mode="baseline", model=f"baseline:{args.strategy}",
                    dataset=args.dataset, git_sha=git_sha(), k=args.k, seed=args.seed)
        run_baseline(cases, args.k, random.Random(args.seed), trace)
    print(run_id)
    return 0


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:.4f}"


def format_metrics(run_id: str, header: dict, m: RunMetrics, served_by: list[str],
                   records: list[CaseRecord]) -> str:
    tokens = "n/a" if m.tokens_per_tp is None else f"{m.tokens_per_tp:.0f}"
    kinds = ", ".join(f"{k} {v:.2f}" for k, v in sorted(m.recall_by_kind.items())) or "-"
    curve = " | ".join(f">={t:.1f} P{p:.2f} R{r:.2f}" for t, p, r in m.pr_curve)
    lines = [
        f"run {run_id}  model={header['model']}  dataset={header['dataset']}  "
        f"served_by={','.join(served_by) or '-'}",
        f"  cases {m.cases} (errored {m.errored})  recall {m.recall:.2f}  "
        f"precision {m.precision:.2f}  F1 {m.f1:.2f}",
        f"  cost {_money(m.cost_usd)}  $/TP {_money(m.cost_per_tp)}  tokens/TP {tokens}",
        f"  tool_errors {m.tool_errors}  parse_failures {m.parse_failures}",
        f"  recall by kind: {kinds}",
        f"  PR curve: {curve}",
    ]
    repeats = sorted({r.repeat for r in records})
    if len(repeats) > 1:
        per = [aggregate([r for r in records if r.repeat == k]).recall for k in repeats]
        spread = max(per) - min(per)
        lines.append(f"  recall per repeat: {', '.join(f'{x:.2f}' for x in per)} "
                     f"(spread {spread:.2f})")
    if len(served_by) > 1:
        lines.append("  WARNING: served by more than one backend; numbers mix providers")
    return "\n".join(lines)


def cmd_report(args) -> int:
    blocks = []
    for run_id in args.run_ids:
        events = read_trace(_trace_path(args.runs_dir, run_id))
        header = next(e for e in events if e["kind"] == "header")
        records = [CaseRecord.from_dict(e["record"]) for e in events if e["kind"] == "case"]
        served = sorted({e["served_by"] for e in events
                         if e["kind"] == "call" and e.get("served_by")})
        blocks.append(format_metrics(run_id, header, aggregate(records), served, records))
    print("\n\n".join(blocks))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whippletree")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a benchmark")
    modes = run.add_subparsers(dest="mode", required=True)

    review = modes.add_parser("review", help="run a reviewer model over a dataset")
    review.add_argument("--dataset", choices=DATASETS, required=True)
    review.add_argument("--model", required=True, help="provider:model-id")
    review.add_argument("--limit", type=int)
    review.add_argument("--repeat", type=int, default=1)
    review.add_argument("--case", help="run one case by id")
    review.add_argument("--routing", help="OpenRouter backends to pin, comma-separated")
    review.add_argument("--runs-dir", default="runs")
    review.set_defaults(func=cmd_review)

    baseline = modes.add_parser("baseline", help="run the random-guess baseline")
    baseline.add_argument("--dataset", choices=DATASETS, required=True)
    baseline.add_argument("--strategy", choices=("random",), default="random")
    baseline.add_argument("--k", type=int, default=3, help="guesses per case")
    baseline.add_argument("--seed", type=int, default=0)
    baseline.add_argument("--limit", type=int)
    baseline.add_argument("--runs-dir", default="runs")
    baseline.set_defaults(func=cmd_baseline)

    report = sub.add_parser("report", help="print metrics for one or more runs")
    report.add_argument("run_ids", nargs="+")
    report.add_argument("--runs-dir", default="runs")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the whole suite and lint**

```bash
uv run pytest
uv run ruff check .
```

Expected: all tests pass; ruff clean. Fix any ruff findings (import order: `uv run ruff check --fix .`).

- [ ] **Step 6: Commit**

```bash
git add src/whippletree/cli.py tests/test_cli.py
git commit -m "feat: CLI with run review/baseline and report"
```

---

### Task 16: CI and README

**Files:**

- Create: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] **Step 1: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run pytest
```

- [ ] **Step 2: Write the README**

`README.md`:

````markdown
# whippletree

A whippletree is the crossbar that balances the pull between several horses hitched to one load. Here the horses are models.

Whippletree is a self-built coding-agent harness. Milestone 1 benchmarks code review across models: a reviewer agent reads a PR-style diff containing one known bug, uses read-only tools on the repository, and submits findings. Whippletree scores them against ground truth and logs every model call.

## Hypotheses

- **H1:** a cheap model plus a verifier gets >= 80% of a frontier model's recall at <= 20% of the cost.
- **H2:** cross-model review catches bugs that self-review misses.
- **H3:** native provider adapters cut cost vs. OpenRouter (prompt caching).

## Run it

```bash
uv sync
git config core.hooksPath .githooks   # gitleaks pre-commit hook
cp .env.example .env                  # add OPENROUTER_API_KEY for OpenRouter models

uv run whippletree run baseline --dataset seeded
uv run whippletree run review --dataset seeded --model ollama:llama3.1:8b
uv run whippletree run review --dataset seeded --model openrouter:google/gemini-2.5-pro --routing Google
uv run whippletree report <run-id> [<run-id> ...]
```

Traces go to `runs/<run-id>.jsonl` (gitignored). Curated results go in `results/`.

## Design choices

- One runtime dependency (`openai`, pinned in `uv.lock`). No LiteLLM, no agent frameworks: fewer supply-chain risks, and the provider differences stay visible.
- OpenRouter routing is pinned per run so a model id isn't silently served by different backends.
- Spec: `docs/superpowers/specs/2026-11-01-whippletree-design.md`.

## License

MIT
````

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "docs: README and CI"
```

---

### Task 17: Live smoke test (local, not CI)

**Files:**

- Create: `tests/test_live.py`

- [ ] **Step 1: Write the live test**

`tests/test_live.py`:

```python
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
```

- [ ] **Step 2: Confirm it's excluded by default, then run it live**

```bash
uv run pytest -q                 # live test deselected
ollama list | grep llama3.1:8b
uv run pytest -m live -v
```

Expected: default run deselects 1 test; live run passes. A `stop` of `no_submit` or `max_steps` still passes: an 8B model fumbling the tool protocol is a result, not a harness bug. Look at the trace and note what happened in the bead.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live.py
git commit -m "test: live Ollama smoke test"
```

---

### Task 18: Publish to GitHub (confirm with the user first)

This makes the repo public. Ask before running.

- [ ] **Step 1: Full-history secret scan**

```bash
gitleaks git --redact --no-banner -v .
```

Expected: `no leaks found`. Stop and report if anything is found.

- [ ] **Step 2: Create and push (after the user says yes)**

```bash
gh repo create MichaelPaulukonis/whippletree --public --source . --push \
  --description "Self-built coding-agent harness that benchmarks cross-model code review"
bd dolt push --yes
git push
git ls-remote origin | grep dolt
```

Expected: repo exists, CI run starts, `refs/dolt/data` present.

- [ ] **Step 3: Check CI**

```bash
gh run watch --exit-status
```

Expected: green.
