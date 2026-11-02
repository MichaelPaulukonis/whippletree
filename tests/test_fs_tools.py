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
