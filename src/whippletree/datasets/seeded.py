"""Hand-seeded cases: datasets/seeded/<id>/{before/, after/, truth.json}."""

import json
import re
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
    """Unified diff of two sibling trees, with a/ and b/ paths relative to each tree."""
    if before.parent != after.parent:
        raise ValueError(f"trees must be siblings: {before} vs {after}")
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", "diff", "--no-index", "--no-color",
         before.name, after.name],
        cwd=before.parent,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):  # 1 just means "there are differences"
        raise RuntimeError(f"git diff failed: {proc.stderr}")
    return _strip_tree_names(proc.stdout, before.name, after.name)


_HEADERS = ("diff --git ", "--- ", "+++ ", "rename from ", "rename to ", "Binary files ")


def _strip_tree_names(diff: str, before: str, after: str) -> str:
    """Drop the tree dir from header paths only; hunk content is never touched.

    git --no-index can put either tree under either prefix (a new file is a/after/x).
    """
    names = f"(?:{re.escape(before)}|{re.escape(after)})/"
    # A path starts after a space or an opening quote.
    prefixed = re.compile(rf'(?<=[\s"])([ab]/){names}')
    renamed = re.compile(rf'^(rename (?:from|to) "?){names}')
    out = []
    in_header = False
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            in_header = True
        elif line.startswith("@@"):
            in_header = False
        if in_header and line.startswith(_HEADERS):
            line = renamed.sub(r"\1", prefixed.sub(r"\1", line))
        out.append(line)
    return "".join(out)
