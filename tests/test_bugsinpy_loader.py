"""load_bugsinpy end to end, against local fixture repos (no network)."""

from pathlib import Path

from tests.gitrepo import commit, git, init_repo, padded_history
from whippletree.case import Range
from whippletree.datasets.bugsinpy import Skip, load_bugsinpy, read_info

TEST_PATCH = ("diff --git a/tests/test_app.py b/tests/test_app.py\n"
              "--- a/tests/test_app.py\n+++ b/tests/test_app.py\n"
              "@@ -1 +1 @@\n-a\n+b\n")


def _metadata(tmp_path: Path, project_url: str, bugs: dict[str, tuple[str, str]]) -> Path:
    """A fake BugsInPy repo: bugs maps bug number -> (buggy sha, patch)."""
    meta = init_repo(tmp_path / "meta")
    files = {"projects/demo/project.info": f'github_url="{project_url}"\nstatus="OK"'}
    for n, (sha, patch) in bugs.items():
        files[f"projects/demo/bugs/{n}/bug.info"] = (
            f'python_version="3.8.3"\nbuggy_commit_id="{sha}"\nfixed_commit_id="x"')
        files[f"projects/demo/bugs/{n}/bug_patch.txt"] = patch
    commit(meta, files)
    return meta


def _load(tmp_path, bugs, project_url=None, **kwargs):
    s = padded_history(tmp_path / "upstream")
    meta = _metadata(tmp_path, project_url or str(tmp_path / "upstream"),
                     {n: (sha or s["B"], patch or s["patch"]) for n, (sha, patch) in bugs.items()})
    cases, skipped = load_bugsinpy(cache=tmp_path / "cache", projects=("demo",),
                                   metadata_url=str(meta), min_lines=50, **kwargs)
    return s, cases, skipped


def test_read_info_handles_quotes_and_missing_newline(tmp_path):
    p = tmp_path / "bug.info"
    p.write_text('a="1"\nb = "two words"\nnot a pair')
    assert read_info(p) == {"a": "1", "b": "two words"}


def test_builds_case_with_checkout_at_buggy(tmp_path):
    s, cases, skipped = _load(tmp_path, {"1": (None, None)})
    assert skipped == []
    (case,) = cases
    assert case.id == "bugsinpy/demo/1"
    assert case.dataset == "bugsinpy"
    assert case.ground_truth == (Range("app.py", 2, 2),)
    assert case.padding.base == s["c1"]
    assert git(case.checkout_path, "rev-parse", "HEAD").strip() == s["B"]
    assert "return x + 2" in (case.checkout_path / "app.py").read_text()
    assert "+    return x + 2" in case.diff


def test_bad_cases_are_skipped_with_reasons_not_raised(tmp_path):
    _, cases, skipped = _load(tmp_path, {
        "1": (None, None),
        "2": (None, TEST_PATCH),
        "3": ("0" * 40, None),
        "4": (None, "not a patch\n"),
    })
    assert [c.id for c in cases] == ["bugsinpy/demo/1"]
    assert skipped == [Skip("bugsinpy/demo/2", "patch-touches-tests"),
                       Skip("bugsinpy/demo/3", "commit-missing"),
                       Skip("bugsinpy/demo/4", "no-ground-truth")]
    assert not (tmp_path / "cache" / "checkouts" / "demo-2").exists()


def test_bugs_sorted_numerically(tmp_path):
    _, cases, _ = _load(tmp_path, {"10": (None, None), "2": (None, None)})
    assert [c.id for c in cases] == ["bugsinpy/demo/2", "bugsinpy/demo/10"]


def test_limit_stops_early(tmp_path):
    _, cases, skipped = _load(tmp_path, {"1": (None, TEST_PATCH), "2": (None, None),
                                         "3": (None, None)}, limit=1)
    assert [c.id for c in cases] == ["bugsinpy/demo/2"]
    assert skipped == [Skip("bugsinpy/demo/1", "patch-touches-tests")]
    assert not (tmp_path / "cache" / "checkouts" / "demo-3").exists()


def test_case_id_builds_one_case_from_any_project(tmp_path):
    _load(tmp_path, {"1": (None, None), "3": (None, None)}, limit=1)
    cases, skipped = load_bugsinpy(cache=tmp_path / "cache", projects=("other",),
                                   metadata_url=str(tmp_path / "meta"), min_lines=50,
                                   case_id="bugsinpy/demo/3")
    assert [c.id for c in cases] == ["bugsinpy/demo/3"]
    assert skipped == []
    assert load_bugsinpy(cache=tmp_path / "cache", metadata_url=str(tmp_path / "meta"),
                         case_id="bugsinpy/nope/1") == ([], [])


def test_second_load_reuses_cache(tmp_path):
    _, first, _ = _load(tmp_path, {"1": (None, None)})
    again, skipped = load_bugsinpy(cache=tmp_path / "cache", projects=("demo",),
                                   metadata_url=str(tmp_path / "meta"), min_lines=50)
    assert skipped == []
    assert again == first


def test_clone_failure_skips_whole_project(tmp_path):
    _, cases, skipped = _load(tmp_path, {"1": (None, None)},
                              project_url=str(tmp_path / "nope"))
    assert cases == []
    assert skipped == [Skip("bugsinpy/demo/1", "clone-failed")]
    assert not (tmp_path / "cache" / "repos" / "demo").exists()


def test_patch_that_does_not_fit_buggy_is_skipped(tmp_path):
    other_patch = ("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
                   "@@ -1 +1 @@\n-nothing like this\n+here\n")
    _, _, skipped = _load(tmp_path, {"1": (None, other_patch)})
    assert skipped == [Skip("bugsinpy/demo/1", "patch-does-not-apply-to-buggy")]


def test_limit_does_not_clone_next_project(tmp_path):
    s = padded_history(tmp_path / "upstream")
    meta = _metadata(tmp_path, str(tmp_path / "upstream"), {"1": (s["B"], s["patch"])})
    commit(meta, {"projects/demo2/project.info": f'github_url="{tmp_path / "other"}"',
                  "projects/demo2/bugs/1/bug.info": f'buggy_commit_id="{s["B"]}"',
                  "projects/demo2/bugs/1/bug_patch.txt": s["patch"]})
    cache = tmp_path / "cache"
    cases, skipped = load_bugsinpy(cache=cache, projects=("demo", "demo2"),
                                   metadata_url=str(meta), min_lines=50, limit=1)
    assert [c.id for c in cases] == ["bugsinpy/demo/1"]
    assert skipped == []
    assert not (cache / "repos" / "demo2").exists()
