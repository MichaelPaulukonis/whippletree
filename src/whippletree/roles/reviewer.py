"""The reviewer role: a prompt, read-only tools, and a terminal submit_findings tool."""

import re
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
- confidence: a number from 0 to 1

The review gets at most {max_steps} model turns (each of your replies is one turn).
Call submit_findings before you run out; anything not submitted is lost."""

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
        if isinstance(line, float) and line.is_integer():
            line = int(line)  # some models send 12.0 for an integer field
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


def build_system_prompt(limits: Limits | None = None) -> str:
    # Not str.format: the prompt may grow literal braces (e.g. a JSON example).
    return SYSTEM_PROMPT.replace("{max_steps}", str((limits or Limits()).max_steps))


def build_user_message(case: Case) -> str:
    # The fence must be longer than any backtick run in the diff, or the diff can close it.
    longest = max((len(m) for m in re.findall(r"`+", case.diff)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"Review this pull request.\n\n{fence}diff\n{case.diff}\n{fence}"


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
        {"role": "system", "content": build_system_prompt(limits)},
        {"role": "user", "content": build_user_message(case)},
    ]
    result = run(provider, model, messages, tools, limits=limits, settings=settings,
                 on_call=on_call)
    findings = result.result if result.stop == "done" else []
    return ReviewResult(findings=findings, loop=result)
