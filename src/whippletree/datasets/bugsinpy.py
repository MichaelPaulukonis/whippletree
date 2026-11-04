"""BugsInPy loader: turns a real bug-fix commit into a padded-diff review case.

A padded diff is the PR-style diff the reviewer sees: the buggy commit B is diffed against an
older base X so the diff carries enough unrelated change to hide the bug among realistic noise.
Ground truth comes from the project's fix patch (buggy B -> fixed F), expressed in B's line
numbers, which are the head-side line numbers of the padded diff.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from whippletree.baseline import changed_lines as diff_changed_lines
from whippletree.case import Case, Padding, Range
from whippletree.errors import WhippletreeError

MIN_LINES, MAX_LINES, MAX_WALK = 80, 250, 50
CACHE = Path.home() / ".cache" / "whippletree" / "bugsinpy"
METADATA_URL = "https://github.com/soarsmu/BugsInPy.git"
DEFAULT_PROJECTS = ("PySnooper", "cookiecutter", "httpie", "sanic", "tqdm", "thefuck")

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*$|_test\.py$")
# Belt and braces: _git already isolates user config; these pin the diff format regardless.
_DIFF_FLAGS = ("--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/")


class SkipCase(Exception):
    """A case that can't be built. str(e) is the skip reason. Becomes a Skip; never sinks the load."""


class GitError(Exception):
    """A git command failed."""


def parse_patch_ranges(patch: str) -> tuple[Range, ...]:
    """One Range per contiguous change run in the fix (B -> F), in B's (pre-image) line numbers.

    A run with removed lines is kind="modification" spanning those lines. A run with only
    added lines is kind="deletion" at the line before the insertion (clamped to 1). Context
    lines end a run. Files the fix creates (--- /dev/null) give no range.
    """
    ranges: list[Range] = []
    path: str | None = None
    old_ln = old_rem = new_rem = 0
    # Current run: first/last removed line (or None) and where an add-only run would sit.
    first_rm: int | None = None
    last_rm = 0
    add_at: int | None = None

    def flush() -> None:
        nonlocal first_rm, add_at
        if path is not None:
            if first_rm is not None:
                ranges.append(Range(path, first_rm, last_rm, "modification"))
            elif add_at is not None:
                at = max(add_at - 1, 1)
                ranges.append(Range(path, at, at, "deletion"))
        first_rm = add_at = None

    for line in patch.splitlines():
        in_hunk = old_rem > 0 or new_rem > 0
        if not in_hunk:
            if line.startswith("--- "):
                flush()
                name = line[4:].split("\t")[0]
                path = name[2:] if name.startswith("a/") else None
                continue
            m = _HUNK.match(line)
            if m:
                flush()
                start = int(m.group(1))
                old_rem = 1 if m.group(2) is None else int(m.group(2))
                new_rem = 1 if m.group(3) is None else int(m.group(3))
                # count 0: start is the line before the insertion
                old_ln = start + 1 if old_rem == 0 else start
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("-"):
            if first_rm is None:
                first_rm = old_ln
            last_rm = old_ln
            old_ln += 1
            old_rem -= 1
        elif line.startswith("+"):
            if add_at is None:
                add_at = old_ln
            new_rem -= 1
        else:  # context; a bare empty line is context whose leading space was stripped
            flush()
            old_ln += 1
            old_rem -= 1
            new_rem -= 1
        if old_rem <= 0 and new_rem <= 0:
            flush()
            old_rem = new_rem = 0
    flush()
    return tuple(ranges)


def touches_tests(patch: str) -> bool:
    """True if any --- a/ or +++ b/ path looks like test code or test data."""
    for line in patch.splitlines():
        if line.startswith(("--- a/", "+++ b/")) and _TEST_PATH.search(line[6:].split("\t")[0]):
            return True
    return False


def _git(repo: Path, *args: str, input: str | None = None, env: dict[str, str] | None = None) -> str:
    """Run git in repo, return stdout; raise GitError(f"git {args[0]}: {stderr}") on nonzero exit."""
    base_env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    proc = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], cwd=repo, input=input,
        stdin=subprocess.DEVNULL if input is None else None,
        capture_output=True, encoding="utf-8", errors="surrogateescape", env=base_env,
    )
    if proc.returncode != 0:
        raise GitError(f"git {args[0]}: {proc.stderr.strip()}")
    return proc.stdout


def changed_lines(repo: Path, a: str, b: str) -> int:
    """Added + deleted lines between two tree-ishes (git diff --numstat). Binary files count 0."""
    total = 0
    for row in _git(repo, "diff", "--numstat", *_DIFF_FLAGS, a, b).splitlines():
        added, deleted, _ = row.split("\t", 2)
        if added != "-":  # binary files show "-"
            total += int(added) + int(deleted)
    return total


def pick_base(repo: Path, buggy: str, min_lines: int = MIN_LINES, max_lines: int = MAX_LINES,
              max_walk: int = MAX_WALK) -> tuple[str, tuple[str, ...]]:
    """(base, commits) for the smallest K whose B~K..B reaches min_lines.

    commits are B~K..B's K commits, oldest first (B last). Walks first-parent from B, at most
    max_walk commits. Raises SkipCase: "no-history" (B is a root), "bug-commit-over-cap"
    (K=1 already > max_lines), "padding-under-min-lines" (cap, root, or max_walk reached first).
    """
    chain = _git(repo, "rev-list", "--first-parent", f"--max-count={max_walk + 1}", buggy).split()
    if len(chain) < 2:
        raise SkipCase("no-history")
    for k in range(1, len(chain)):
        n = changed_lines(repo, chain[k], buggy)
        if n > max_lines:
            raise SkipCase("bug-commit-over-cap" if k == 1 else "padding-under-min-lines")
        if n >= min_lines:
            return chain[k], tuple(reversed(chain[:k]))
    raise SkipCase("padding-under-min-lines")


def apply_onto(repo: Path, base: str, patch: str) -> str | None:
    """Tree sha of `base` (commit or tree) with `patch` applied, or None if it doesn't apply.

    Uses a throwaway index (GIT_INDEX_FILE in a TemporaryDirectory): read-tree base,
    apply --cached (patch on stdin), write-tree. The repo's own index and checkout are untouched.
    """
    if not patch.endswith("\n"):
        patch += "\n"  # git apply rejects a patch without a final newline as corrupt
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(repo, "read-tree", base, env=env)
        try:
            _git(repo, "apply", "--cached", input=patch, env=env)
        except GitError:
            return None
        return _git(repo, "write-tree", env=env).strip()


def build_padded(repo: Path, buggy: str, patch: str, min_lines: int = MIN_LINES,
                 max_lines: int = MAX_LINES) -> tuple[str, Padding]:
    """`git diff X B` (X = pick_base's base + fix) and its Padding record.

    Raises SkipCase: anything from pick_base, "fix-does-not-apply", "padding-out-of-bounds"
    (final X..B size outside [min_lines, max_lines]). Padding.changed_lines is the X..B size.
    """
    base, commits = pick_base(repo, buggy, min_lines, max_lines)
    x = apply_onto(repo, base, patch)
    if x is None:
        raise SkipCase("fix-does-not-apply")
    size = changed_lines(repo, x, buggy)
    if not min_lines <= size <= max_lines:
        raise SkipCase("padding-out-of-bounds")
    diff = _git(repo, "diff", *_DIFF_FLAGS, x, buggy)
    return diff, Padding(base=base, commits=commits, changed_lines=size)


@dataclass(frozen=True)
class Skip:
    id: str
    reason: str


def read_info(path: Path) -> dict[str, str]:
    """BugsInPy .info files: key="value" lines (spaces around = allowed); other lines ignored."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    for line in text.splitlines():
        m = re.match(r'^\s*(\w+)\s*=\s*"(.*)"\s*$', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def ensure_clone(url: str, dest: Path, *extra: str) -> Path:
    """Clone url to dest once (extra = clone flags); reuse if dest/.git exists.

    Wipe a partial dest before and after a failed clone. Print "whippletree: cloning <url>" to stderr.
    """
    if (dest / ".git").exists():
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    # Clone beside dest and rename on success, so a killed clone never leaves a reusable dest/.git.
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"whippletree: cloning {url}", file=sys.stderr)
    try:
        _git(dest.parent, "clone", "-q", *extra, url, str(tmp))
    except GitError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    tmp.rename(dest)
    return dest


def ensure_checkout(repo: Path, dest: Path, commit: str) -> Path:
    """Detached worktree of repo at commit. Reuse if HEAD already matches; otherwise wipe dest,
    `git worktree prune`, then `git worktree add --force --detach`."""
    if dest.exists():
        try:
            if _git(dest, "rev-parse", "HEAD").strip() == commit:
                return dest
        except GitError:
            pass
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "prune")
    _git(repo, "worktree", "add", "--force", "--detach", str(dest), commit)
    return dest


def build_case(case_id: str, repo: Path, bug_dir: Path, checkout: Path,
               min_lines: int = MIN_LINES, max_lines: int = MAX_LINES) -> Case:
    """One padded case, checkout at B. Raises SkipCase. Check order: no-ground-truth,
    patch-touches-tests, commit-missing, patch-does-not-apply-to-buggy, build_padded's reasons,
    bug-not-in-diff. Create the worktree last, so skipped cases leave no checkout behind."""
    patch = (bug_dir / "bug_patch.txt").read_text(encoding="utf-8", errors="surrogateescape")
    ranges = parse_patch_ranges(patch)
    if not ranges:
        raise SkipCase("no-ground-truth")
    if touches_tests(patch):
        raise SkipCase("patch-touches-tests")
    sha = read_info(bug_dir / "bug.info").get("buggy_commit_id", "")
    try:
        buggy = _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").strip()
    except GitError:
        raise SkipCase("commit-missing") from None
    if apply_onto(repo, buggy, patch) is None:
        raise SkipCase("patch-does-not-apply-to-buggy")
    diff, padding = build_padded(repo, buggy, patch, min_lines, max_lines)
    touched = diff_changed_lines(diff)
    for r in ranges:
        if not any(f == r.file and r.start <= ln <= r.end for f, ln in touched):
            raise SkipCase("bug-not-in-diff")
    ensure_checkout(repo, checkout, buggy)
    return Case(id=case_id, dataset="bugsinpy", checkout_path=checkout, diff=diff,
                ground_truth=ranges, padding=padding)


def _bug_numbers(project_dir: Path) -> list[str]:
    bugs = project_dir / "bugs"
    if not bugs.is_dir():
        return []
    return sorted((p.name for p in bugs.iterdir() if p.is_dir() and p.name.isdigit()), key=int)


def load_bugsinpy(cache: Path = CACHE, projects: tuple[str, ...] = DEFAULT_PROJECTS,
                  metadata_url: str = METADATA_URL, min_lines: int = MIN_LINES,
                  max_lines: int = MAX_LINES, case_id: str | None = None,
                  limit: int | None = None) -> tuple[list[Case], list[Skip]]:
    """Cases in (project, numeric bug) order, plus a Skip for each attempted case that failed.

    limit: stop as soon as that many cases have built. case_id ("bugsinpy/<proj>/<n>"):
    build only that bug, from any BugsInPy project; unknown id -> ([], []).
    """
    try:
        meta = ensure_clone(metadata_url, cache / "meta", "--depth", "1")
    except GitError as e:
        raise WhippletreeError(f"could not fetch BugsInPy metadata: {e}") from e

    wanted_bug: str | None = None
    if case_id is not None:
        parts = case_id.split("/")
        if len(parts) != 3 or parts[0] != "bugsinpy":
            return [], []
        wanted_bug = parts[2]
        projects = (parts[1],)

    cases: list[Case] = []
    skipped: list[Skip] = []
    if limit is not None and limit <= 0:
        return cases, skipped
    for project in projects:
        project_dir = meta / "projects" / project
        numbers = _bug_numbers(project_dir)
        if wanted_bug is not None:
            numbers = [n for n in numbers if n == wanted_bug]
        if not numbers:
            continue
        try:
            url = read_info(project_dir / "project.info")["github_url"].rstrip("/")
            repo = ensure_clone(url, cache / "repos" / project, "--filter=blob:none")
        except (GitError, KeyError, OSError):
            skipped.extend(Skip(f"bugsinpy/{project}/{n}", "clone-failed") for n in numbers)
            continue
        for n in numbers:
            cid = f"bugsinpy/{project}/{n}"
            try:
                cases.append(build_case(cid, repo, project_dir / "bugs" / n,
                                        cache / "checkouts" / f"{project}-{n}",
                                        min_lines, max_lines))
                if limit is not None and len(cases) >= limit:
                    return cases, skipped
            except SkipCase as e:
                skipped.append(Skip(cid, str(e)))
            except GitError as e:
                skipped.append(Skip(cid, f"git-error: {e}"))
            except OSError as e:
                skipped.append(Skip(cid, f"unreadable: {e}"))
    return cases, skipped
