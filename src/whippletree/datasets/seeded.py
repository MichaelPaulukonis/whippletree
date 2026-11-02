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
