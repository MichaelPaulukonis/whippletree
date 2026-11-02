import pytest

from whippletree.errors import WhippletreeError
from whippletree.providers.base import Usage, parse_model


def test_parse_model_splits_on_first_colon():
    assert parse_model("ollama:llama3.1:8b") == ("ollama", "llama3.1:8b")
    assert parse_model("openrouter:google/gemini-2.5-pro") == ("openrouter", "google/gemini-2.5-pro")


@pytest.mark.parametrize("bad", ["llama3", ":x", "ollama:"])
def test_parse_model_rejects_bad_specs(bad):
    with pytest.raises(WhippletreeError):
        parse_model(bad)


def test_usage_total():
    assert Usage(input=3, output=4, cached=2).total == 7
