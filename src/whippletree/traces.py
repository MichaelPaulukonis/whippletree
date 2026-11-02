"""Append-only JSONL run traces: one header, then call and case events."""

import json
import secrets
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path

from whippletree.errors import WhippletreeError


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
        try:
            self._file = path.open("x")
        except FileExistsError as e:
            raise WhippletreeError(f"trace already exists: {path}") from e

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
    """Parse a trace. An unparsable final line is a torn write and is skipped; any other raises."""
    numbered = [(n, line) for n, line in enumerate(path.read_text().splitlines(), 1)
                if line.strip()]
    events = []
    for i, (n, line) in enumerate(numbered):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            if i == len(numbered) - 1:
                break
            raise ValueError(f"{path}: line {n} is not valid JSON: {e}") from e
    return events
