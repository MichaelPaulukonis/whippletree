"""OpenRouter and Ollama, both spoken through the openai SDK.

The SDK's own retries are off (max_retries=0) so the loop does retries and can
count them.
"""

import os

import openai

from whippletree.providers.base import ProviderError, Response, ToolCall, TransientError, Usage

# name -> (base_url, env var holding the API key; None means no key needed)
ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}


class OpenAICompatProvider:
    def __init__(self, name: str, client=None, routing: list[str] | None = None):
        if name not in ENDPOINTS:
            raise ProviderError(f"unknown provider {name!r}")
        self.name = name
        self.routing = routing
        if client is None:
            base_url, key_var = ENDPOINTS[name]
            api_key = "ollama"
            if key_var:
                api_key = os.environ.get(key_var, "")
                if not api_key:
                    raise ProviderError(f"{key_var} is not set (put it in .env)")
            client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self.client = client

    def build_request(self, messages, tools, model, settings) -> dict:
        req = {"model": model, "messages": messages, **settings}
        if tools:
            req["tools"] = tools
        if self.name == "openrouter":
            extra = {"usage": {"include": True}}
            if self.routing:
                # Pin the backend so one model id isn't silently served by different hosts.
                extra["provider"] = {"order": self.routing, "allow_fallbacks": False}
            req["extra_body"] = extra
        return req

    def complete(self, messages, tools, model, settings) -> Response:
        req = self.build_request(messages, tools, model, settings)
        try:
            raw = self.client.chat.completions.create(**req)
        except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as e:
            raise TransientError(str(e)) from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(str(e)) from e
            raise ProviderError(str(e)) from e
        return parse_response(raw)


def parse_response(raw) -> Response:
    choice = raw.choices[0]
    msg = choice.message
    calls = [
        ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
        for c in (msg.tool_calls or [])
        if c.type == "function"
    ]
    u = raw.usage
    usage = Usage()
    cost = None
    if u is not None:
        details = u.prompt_tokens_details
        cached = (details.cached_tokens or 0) if details else 0
        usage = Usage(input=u.prompt_tokens, output=u.completion_tokens, cached=cached)
        cost = (u.model_extra or {}).get("cost")  # OpenRouter usage accounting
    return Response(
        text=msg.content or "",
        tool_calls=calls,
        usage=usage,
        stop_reason=choice.finish_reason or "unknown",
        cost_usd=cost,
        served_by=(raw.model_extra or {}).get("provider"),  # OpenRouter: which backend served it
        raw=raw,
    )
