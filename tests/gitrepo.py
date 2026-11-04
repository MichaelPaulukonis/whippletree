"""Throwaway git repos for tests. Real git, no network."""

import subprocess
from pathlib import Path


def git(repo: Path, *args: str, input: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, input=input, check=True,
                          capture_output=True, text=True).stdout


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    for key, value in [("user.email", "t@example.com"), ("user.name", "t"),
                       ("commit.gpgsign", "false")]:
        git(path, "config", key, value)
    return path


def commit(repo: Path, files: dict[str, str], msg: str = "c") -> str:
    """Write files (path -> content), commit everything, return the new sha."""
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").strip()


def lines(n: int, prefix: str = "x") -> str:
    return "".join(f"{prefix}{i}\n" for i in range(n))


APP_BUGGY = "def f(x):\n    return x + 2\n"
APP_FIXED = "def f(x):\n    return x + 1\n"


def padded_history(path: Path, bug_at: int = 0, b_size: int = 30) -> dict[str, str]:
    """c0 (app.py) -> c1, c2 (30-line pad files) -> B (b_size-line pad) -> F (fix).

    bug_at picks the commit that turns app.py's `x` into the buggy `x + 2`
    (0 = c0, 2 = c2, 3 = B). Returns shas plus the B -> F fix patch.
    """
    repo = init_repo(path)
    early = APP_BUGGY if bug_at == 0 else "def f(x):\n    return x\n"
    shas = {"c0": commit(repo, {"app.py": early})}
    shas["c1"] = commit(repo, {"pad1.py": lines(30, "a")})
    shas["c2"] = commit(repo, {"pad2.py": lines(30, "b"),
                               **({"app.py": APP_BUGGY} if bug_at == 2 else {})})
    shas["B"] = commit(repo, {"pad3.py": lines(b_size, "c"),
                              **({"app.py": APP_BUGGY} if bug_at == 3 else {})})
    shas["F"] = commit(repo, {"app.py": APP_FIXED})
    shas["patch"] = git(repo, "diff", shas["B"], shas["F"])
    return shas
