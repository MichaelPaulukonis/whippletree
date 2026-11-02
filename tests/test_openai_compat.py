from types import SimpleNamespace

import httpx2  # openai 3.x ships httpx2, not httpx
import openai
import pytest
from openai.types.chat import ChatCompletion

from whippletree.providers.base import ProviderError, ToolCall, TransientError, Usage
from whippletree.providers.openai_compat import OpenAICompatProvider, parse_response

TOOL_CALL_RESPONSE = {
    "id": "gen-1",
    "object": "chat.completion",
    "created": 1,
    "model": "google/gemini-2.5-pro",
    "provider": "Google",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path": "a.py"}'},
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "prompt_tokens_details": {"cached_tokens": 40},
        "cost": 0.0012,
    },
}

TEXT_RESPONSE = {
    "id": "x",
    "object": "chat.completion",
    "created": 1,
    "model": "llama3.1:8b",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}
    ],
    "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
}


def test_parse_tool_call_response():
    r = parse_response(ChatCompletion.model_validate(TOOL_CALL_RESPONSE))
    assert r.tool_calls == [ToolCall(id="call_1", name="read_file", arguments='{"path": "a.py"}')]
    assert r.usage == Usage(input=100, output=20, cached=40)
    assert r.cost_usd == 0.0012
    assert r.served_by == "Google"
    assert r.stop_reason == "tool_calls"
    assert r.text == ""


def test_parse_text_response_without_cost_or_provider():
    r = parse_response(ChatCompletion.model_validate(TEXT_RESPONSE))
    assert r.text == "hi"
    assert r.tool_calls == []
    assert r.usage == Usage(input=5, output=1, cached=0)
    assert r.cost_usd is None
    assert r.served_by is None


def test_openrouter_request_pins_routing_and_asks_for_cost():
    p = OpenAICompatProvider("openrouter", client=object(), routing=["Google"])
    req = p.build_request([{"role": "user", "content": "x"}], [], "google/gemini-2.5-pro",
                          {"temperature": 0})
    assert req["extra_body"] == {
        "usage": {"include": True},
        "provider": {"order": ["Google"], "allow_fallbacks": False},
    }
    assert req["temperature"] == 0
    assert "tools" not in req


def test_ollama_request_has_no_extra_body_but_passes_tools():
    p = OpenAICompatProvider("ollama", client=object())
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    req = p.build_request([], tools, "llama3.1:8b", {})
    assert "extra_body" not in req
    assert req["tools"] == tools


class FakeCompletions:
    def __init__(self, exc=None, resp=None):
        self.exc, self.resp, self.kwargs = exc, resp, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.resp


def _provider(completions):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAICompatProvider("ollama", client=client)


def _status_error(cls, code):
    request = httpx2.Request("POST", "https://example.test")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(openai.RateLimitError, 429),
        _status_error(openai.InternalServerError, 500),
        openai.APIConnectionError(request=httpx2.Request("POST", "https://example.test")),
    ],
)
def test_retryable_failures_are_transient(exc):
    with pytest.raises(TransientError):
        _provider(FakeCompletions(exc=exc)).complete([], [], "m", {})


def test_bad_request_is_permanent():
    exc = _status_error(openai.BadRequestError, 400)
    with pytest.raises(ProviderError):
        _provider(FakeCompletions(exc=exc)).complete([], [], "m", {})


def test_complete_returns_parsed_response():
    fake = FakeCompletions(resp=ChatCompletion.model_validate(TEXT_RESPONSE))
    r = _provider(fake).complete([{"role": "user", "content": "x"}], [], "llama3.1:8b", {})
    assert r.text == "hi"
    assert fake.kwargs["model"] == "llama3.1:8b"


def test_openrouter_without_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        OpenAICompatProvider("openrouter")
