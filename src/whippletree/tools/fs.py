"""Read-only filesystem tools, confined to the case checkout."""

import re
from pathlib import Path

from whippletree.tools.base import Tool, ToolError
from whippletree.tools.env import ToolEnv

MAX_GREP_MATCHES = 200
MAX_GREP_FILE_BYTES = 1_000_000


def resolve(env: ToolEnv, rel: str) -> Path:
    root = env.checkout_path.resolve()
    try:
        path = (root / rel).resolve()
    except (ValueError, OSError) as e:
        raise ToolError(f"invalid path: {e}") from e
    if path != root and root not in path.parents:
        raise ToolError(f"path escapes the checkout: {rel}")
    if ".git" in path.relative_to(root).parts:
        raise ToolError("access to .git is not allowed")
    return path


def _required(args: dict, key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(f"missing required string argument '{key}'")
    return value


def _optional_int(args: dict, key: str, default: int) -> int:
    if key not in args:
        return default
    value = args[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError(f"argument '{key}' must be an integer")
    return value


def _optional_path(args: dict) -> str:
    if "path" not in args:
        return "."
    return _required(args, "path")


def build_fs_tools(env: ToolEnv) -> list[Tool]:
    root = env.checkout_path.resolve()

    def read_file(args: dict) -> str:
        rel = _required(args, "path")
        path = resolve(env, rel)
        if not path.is_file():
            raise ToolError(f"not a file: {rel}")
        lines = path.read_text(errors="replace").splitlines()
        start = max(_optional_int(args, "start", 1), 1)
        end = min(_optional_int(args, "end", len(lines)), len(lines))
        return "\n".join(f"{n}\t{lines[n - 1]}" for n in range(start, end + 1))

    def list_dir(args: dict) -> str:
        rel = _optional_path(args)
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
        rel = _optional_path(args)
        base = resolve(env, rel)
        if not base.exists():
            raise ToolError(f"not found: {rel}")
        if base.is_file():
            files = [base]
        else:
            files = sorted(
                f
                for f in base.rglob("*")
                if f.is_file()
                and ".git" not in f.relative_to(root).parts
                and root in f.resolve().parents
            )
        out = []
        for f in files:
            try:
                if f.stat().st_size > MAX_GREP_FILE_BYTES:
                    continue
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
