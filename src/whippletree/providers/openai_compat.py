"""OpenRouter and Ollama, both spoken through the openai SDK.

The SDK's own retries are off (max_retries=0) so the loop does retries and can
count them.
"""

import getpass
import os
import subprocess
import uuid

import openai

from whippletree.providers.base import ProviderError, Response, ToolCall, TransientError, Usage

# name -> (base_url, env var holding the API key; None means no key needed)
ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}

# macOS Keychain fallback for OPENROUTER_API_KEY; shared with traction-engine.
KEYCHAIN_SERVICE = "orak-traction-dev"


def keychain_key(service: str) -> str | None:
    """Return the generic password for (current user, service), or None if absent."""
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-a", getpass.getuser(), "-s", service, "-w"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
    except OSError:  # no `security` binary
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


class OpenAICompatProvider:
    """Chat-completions provider for OpenRouter and Ollama via the openai SDK."""

    def __init__(self, name: str, client=None, routing: list[str] | None = None):
        if name not in ENDPOINTS:
            raise ProviderError(f"unknown provider {name!r}")
        self.name = name
        self.routing = routing
        if client is None:
            base_url, key_var = ENDPOINTS[name]
            api_key = "ollama"
            if key_var:
                service = os.environ.get("WHIPPLETREE_KEYCHAIN_SERVICE", KEYCHAIN_SERVICE)
                api_key = os.environ.get(key_var) or keychain_key(service)
                if not api_key:
                    raise ProviderError(
                        f"{key_var} is not set (put it in .env) and no Keychain entry for {service!r}"
                    )
            client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self.client = client

    def build_request(self, messages, tools, model, settings) -> dict:
        req = {**settings, "model": model, "messages": messages}
        extra = dict(settings.get("extra_body") or {})
        if tools:
            req["tools"] = tools
        if self.name == "openrouter":
            extra["usage"] = {"include": True}
            if self.routing:
                # Pin the backend so one model id isn't silently served by different hosts.
                extra["provider"] = {"order": self.routing, "allow_fallbacks": False}
        req.pop("extra_body", None)
        if extra:
            req["extra_body"] = extra
        return req

    def complete(self, messages, tools, model, settings) -> Response:
        req = self.build_request(messages, tools, model, settings)
        try:
            raw = self.client.chat.completions.create(**req)
        except openai.APIConnectionError as e:  # includes timeouts
            raise TransientError(str(e)) from e
        except openai.APIStatusError as e:
            if _is_transient_code(e.status_code):
                raise TransientError(str(e)) from e
            raise ProviderError(str(e)) from e
        except openai.APIError as e:
            raise ProviderError(str(e)) from e
        return parse_response(raw)


def _is_transient_code(code) -> bool:
    """Missing or unrecognised codes count as transient: retrying is the safe guess."""
    if not isinstance(code, int) or isinstance(code, bool):
        return True
    return code in (408, 409, 429) or code >= 500


def _raise_upstream_error(raw, choice=None):
    err = (raw.model_extra or {}).get("error")
    if not err and choice is not None:
        err = (choice.model_extra or {}).get("error")
    err = err or {}
    code = err.get("code") if isinstance(err, dict) else None
    msg = f"upstream error (code {code}): {err}"
    if _is_transient_code(code):
        raise TransientError(msg)
    raise ProviderError(msg)


def parse_response(raw) -> Response:
    if not raw.choices:
        _raise_upstream_error(raw)
    choice = raw.choices[0]
    if choice.finish_reason == "error":
        _raise_upstream_error(raw, choice)
    msg = choice.message
    calls = []
    for c in msg.tool_calls or []:
        kind = getattr(c, "type", None)
        if getattr(c, "function", None) is None or kind not in (None, "function"):
            raise ProviderError(f"unsupported tool call type {kind!r}")
        calls.append(
            ToolCall(id=c.id or f"call_{uuid.uuid4().hex[:12]}", name=c.function.name,
                     arguments=c.function.arguments or "{}")
        )
    # Reasoning must be echoed back in tool loops (Gemini thought signatures, Anthropic thinking).
    msg_extra = msg.model_extra or {}
    extra = {k: msg_extra[k] for k in ("reasoning", "reasoning_details") if msg_extra.get(k)}
    u = raw.usage
    usage = Usage()
    cost = None
    if u is not None:
        details = u.prompt_tokens_details
        cached = (details.cached_tokens or 0) if details else 0
        usage = Usage(input=u.prompt_tokens or 0, output=u.completion_tokens or 0, cached=cached)
        cost = (u.model_extra or {}).get("cost")  # OpenRouter usage accounting
    return Response(
        text=msg.content or "",
        tool_calls=calls,
        usage=usage,
        stop_reason=choice.finish_reason or "unknown",
        cost_usd=cost,
        served_by=(raw.model_extra or {}).get("provider"),  # OpenRouter: which backend served it
        extra=extra,
        raw=raw,
    )
