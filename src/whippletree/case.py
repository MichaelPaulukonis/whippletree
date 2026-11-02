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
