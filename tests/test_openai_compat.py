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


def _payload(**overrides):
    return {**TEXT_RESPONSE, **overrides}


def _no_choices(code):
    err = {"message": "upstream", "code": code} if code is not None else {}
    return ChatCompletion.model_validate(_payload(choices=[], error=err))


@pytest.mark.parametrize("code", [429, 408, 409, 500, 503, None])
def test_empty_choices_with_transient_error(code):
    with pytest.raises(TransientError):
        parse_response(_no_choices(code))


@pytest.mark.parametrize("code", [400, 401, 402, 403])
def test_empty_choices_with_permanent_error(code):
    with pytest.raises(ProviderError) as ei:
        parse_response(_no_choices(code))
    assert not isinstance(ei.value, TransientError)


def test_finish_reason_error_is_classified():
    # "error" is not in the SDK's finish_reason Literal, so build without validation
    raw = ChatCompletion.model_validate(TEXT_RESPONSE)
    raw.choices[0].finish_reason = "error"
    with pytest.raises(TransientError):
        parse_response(raw)
    raw.model_extra["error"] = {"code": 400}
    with pytest.raises(ProviderError):
        parse_response(raw)


def test_tool_call_without_type_is_kept():
    # the SDK models require `type`, so null it after validation (as lenient backends send it)
    raw = ChatCompletion.model_validate(TOOL_CALL_RESPONSE)
    raw.choices[0].message.tool_calls[0].type = None
    assert parse_response(raw).tool_calls == [
        ToolCall(id="call_1", name="read_file", arguments='{"path": "a.py"}')
    ]


def test_tool_call_of_other_type_is_surfaced():
    raw = ChatCompletion.model_validate(TOOL_CALL_RESPONSE)
    raw.choices[0].message.tool_calls[0].type = "custom"
    with pytest.raises(ProviderError, match="custom"):
        parse_response(raw)


def test_empty_tool_call_ids_get_index_fallback():
    raw = ChatCompletion.model_validate(TOOL_CALL_RESPONSE)
    first = raw.choices[0].message.tool_calls[0]
    calls = [first.model_copy(update={"id": i}) for i in (None, "", "real")]
    raw.choices[0].message.tool_calls = calls
    r = parse_response(raw)
    assert [c.id for c in r.tool_calls] == ["call_0", "call_1", "real"]


@pytest.mark.parametrize("code", [408, 409])
def test_extra_transient_status_codes(code):
    exc = openai.APIStatusError(
        "boom", response=httpx2.Response(code, request=httpx2.Request("POST", "https://e.test")),
        body=None)
    with pytest.raises(TransientError):
        _provider(FakeCompletions(exc=exc)).complete([], [], "m", {})


def test_other_sdk_errors_become_provider_error():
    exc = openai.APIResponseValidationError(
        httpx2.Response(200, request=httpx2.Request("POST", "https://e.test")), body=None)
    with pytest.raises(ProviderError) as ei:
        _provider(FakeCompletions(exc=exc)).complete([], [], "m", {})
    assert not isinstance(ei.value, TransientError)


def test_none_token_counts_become_zero():
    raw = ChatCompletion.model_validate(TEXT_RESPONSE)
    raw.usage.prompt_tokens = None
    raw.usage.completion_tokens = None
    assert parse_response(raw).usage == Usage(0, 0, 0)


def test_settings_cannot_override_reserved_keys_and_extra_body_merges():
    p = OpenAICompatProvider("openrouter", client=object())
    req = p.build_request([{"role": "user", "content": "x"}], [], "real-model",
                          {"model": "evil", "messages": [], "extra_body": {"top_k": 5,
                           "usage": {"include": False}}})
    assert req["model"] == "real-model"
    assert req["messages"] == [{"role": "user", "content": "x"}]
    assert req["extra_body"] == {"top_k": 5, "usage": {"include": True}}


def test_extra_body_setting_kept_on_ollama():
    p = OpenAICompatProvider("ollama", client=object())
    req = p.build_request([], [], "m", {"extra_body": {"top_k": 5}})
    assert req["extra_body"] == {"top_k": 5}
