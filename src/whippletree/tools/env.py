"""Where a case's tools act. 1a: a local checkout. 1b adds a sandbox handle."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolEnv:
    checkout_path: Path
