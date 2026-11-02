import pytest

from whippletree.tools.base import ToolError
from whippletree.tools.env import ToolEnv
from whippletree.tools.fs import build_fs_tools


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("one\ntwo\nthree\nfour\n")
    (tmp_path / "b.txt").write_text("hello two\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: two\n")
    return {t.name: t for t in build_fs_tools(ToolEnv(tmp_path))}


def test_read_file_numbers_lines(tools):
    assert tools["read_file"].fn({"path": "pkg/a.py"}) == "1\tone\n2\ttwo\n3\tthree\n4\tfour"


def test_read_file_line_range(tools):
    assert tools["read_file"].fn({"path": "pkg/a.py", "start": 2, "end": 3}) == "2\ttwo\n3\tthree"


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "pkg/../../x"])
def test_paths_cannot_escape_checkout(tools, path):
    with pytest.raises(ToolError, match="escapes"):
        tools["read_file"].fn({"path": path})


def test_read_missing_file_is_tool_error(tools):
    with pytest.raises(ToolError, match="not a file"):
        tools["read_file"].fn({"path": "nope.py"})


def test_missing_required_argument_is_tool_error(tools):
    with pytest.raises(ToolError, match="path"):
        tools["read_file"].fn({})


def test_list_dir_hides_git(tools):
    assert tools["list_dir"].fn({}) == "b.txt\npkg/"


def test_grep_reports_path_and_line(tools):
    assert tools["grep"].fn({"pattern": "two"}) == "b.txt:1:hello two\npkg/a.py:2:two"


def test_grep_bad_regex_is_tool_error(tools):
    with pytest.raises(ToolError, match="regex"):
        tools["grep"].fn({"pattern": "("})


def test_tool_schema_shape(tools):
    schema = tools["read_file"].schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "read_file"
    assert schema["function"]["parameters"]["required"] == ["path"]


def test_grep_does_not_follow_file_symlink_out_of_checkout(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret").write_text("TOPSECRET\n")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "link.txt").symlink_to(outside / "secret")
    (checkout / "real.txt").write_text("plain\n")
    (checkout / "inner.txt").symlink_to(checkout / "real.txt")
    grep = {t.name: t for t in build_fs_tools(ToolEnv(checkout))}["grep"]
    assert grep.fn({"pattern": "TOPSECRET"}) == "(no matches)"
    assert "inner.txt:1:plain" in grep.fn({"pattern": "plain"})


@pytest.mark.parametrize("bad", ["abc", None, "10", True, 1.5])
@pytest.mark.parametrize("key", ["start", "end"])
def test_read_file_bad_range_is_tool_error(tools, key, bad):
    with pytest.raises(ToolError, match=key):
        tools["read_file"].fn({"path": "pkg/a.py", key: bad})


@pytest.mark.parametrize("tool", ["list_dir", "grep"])
@pytest.mark.parametrize("bad", [5, "", None])
def test_optional_path_must_be_nonempty_string(tools, tool, bad):
    with pytest.raises(ToolError, match="path"):
        tools[tool].fn({"pattern": "x", "path": bad})


def test_nul_in_path_is_tool_error(tools):
    with pytest.raises(ToolError):
        tools["read_file"].fn({"path": "a\x00b"})


@pytest.mark.parametrize("path", [".git/HEAD", ".git", "pkg/../.git/HEAD"])
def test_git_dir_is_inaccessible(tools, path):
    with pytest.raises(ToolError, match=r"\.git"):
        tools["read_file"].fn({"path": path})


def test_grep_works_when_checkout_lives_under_git_named_dir(tmp_path):
    checkout = tmp_path / ".git" / "wt" / "checkout"
    checkout.mkdir(parents=True)
    (checkout / "f.txt").write_text("needle\n")
    grep = {t.name: t for t in build_fs_tools(ToolEnv(checkout))}["grep"]
    assert grep.fn({"pattern": "needle"}) == "f.txt:1:needle"


def test_grep_nonexistent_path_is_tool_error(tools):
    with pytest.raises(ToolError, match="not found"):
        tools["grep"].fn({"pattern": "x", "path": "nope"})


def test_grep_skips_large_files(tools, monkeypatch):
    monkeypatch.setattr("whippletree.tools.fs.MAX_GREP_FILE_BYTES", 12)
    # b.txt (10 bytes) is searched; pkg/a.py (19 bytes) is skipped
    assert tools["grep"].fn({"pattern": "two"}) == "b.txt:1:hello two"
