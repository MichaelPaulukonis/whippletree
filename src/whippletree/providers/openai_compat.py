"""OpenRouter and Ollama, both spoken through the openai SDK.

The SDK's own retries are off (max_retries=0) so the loop does retries and can
count them.
"""

import getpass
import json
import os
import subprocess
import sys
import urllib.request
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit

import openai

from whippletree.providers.base import ProviderError, Response, ToolCall, TransientError, Usage

# name -> (base_url, env var holding the API key; None means no key needed).
# Ollama's base_url is None here: it comes from OLLAMA_HOST at construction time.
ENDPOINTS = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": (None, None),
}

# Rough prompt-size estimate for the Ollama context guard. Real ratios run ~4-5 chars/token
# for English and ~3 for code/JSON, so 3 errs toward refusing rather than truncating.
CHARS_PER_TOKEN = 3


def ollama_host() -> str:
    """OLLAMA_HOST as the Ollama CLI reads it: scheme and port optional."""
    host = os.environ.get("OLLAMA_HOST") or "localhost:11434"
    if "://" not in host:
        host = "http://" + host
    host = host.rstrip("/")
    if urlsplit(host).port is None:
        host += ":11434"
    return host


def ollama_context_length(model: str, host: str | None = None) -> int | None:
    """The context window Ollama will actually run `model` with (not its trained maximum).

    Loads the model first (an empty generate does that), then reads /api/ps. None on failure.
    """
    host = host or ollama_host()
    try:
        load = urllib.request.Request(f"{host}/api/generate", json.dumps({"model": model}).encode(),
                                      {"Content-Type": "application/json"})
        urllib.request.urlopen(load, timeout=120).read()
        with urllib.request.urlopen(f"{host}/api/ps", timeout=10) as r:
            running = json.load(r).get("models", [])
    except (OSError, ValueError):
        return None
    for m in running:
        if model in (m.get("name"), m.get("model")):
            return m.get("context_length")
    return None

# macOS Keychain fallback for OPENROUTER_API_KEY (whippletree-only key, own budget).
KEYCHAIN_SERVICE = "whippletree-or-api-key"


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

    def __init__(self, name: str, client=None, routing: list[str] | None = None,
                 context_lookup: Callable[[str], int | None] | None = None):
        if name not in ENDPOINTS:
            raise ProviderError(f"unknown provider {name!r}")
        self.name = name
        self.routing = routing
        # Only Ollama truncates silently; a real client gets the real lookup by default.
        if context_lookup is None and name == "ollama" and client is None:
            context_lookup = ollama_context_length
        self.context_lookup = context_lookup
        self._context: dict[str, int | None] = {}
        if client is None:
            base_url, key_var = ENDPOINTS[name]
            if name == "ollama":
                base_url = ollama_host() + "/v1"
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

    def _check_context(self, messages, tools, model) -> None:
        if self.context_lookup is None:
            return
        if model not in self._context:
            self._context[model] = self.context_lookup(model)
            if self._context[model] is None:
                print(f"warning: could not read Ollama context length for {model}; "
                      f"prompt truncation will go undetected", file=sys.stderr)
        ctx = self._context[model]
        if ctx is None:
            return
        estimate = (len(json.dumps(messages)) + len(json.dumps(tools))) // CHARS_PER_TOKEN
        if estimate > ctx:
            raise ProviderError(
                f"prompt (~{estimate} tokens est.) exceeds Ollama context ({ctx}); Ollama would "
                f"silently drop its start. Restart Ollama with a larger OLLAMA_CONTEXT_LENGTH."
            )

    def complete(self, messages, tools, model, settings) -> Response:
        self._check_context(messages, tools, model)
        req = self.build_request(messages, tools, model, settings)
        try:
            raw = self.client.chat.completions.create(**req)
        except openai.APIConnectionError as e:  # includes timeouts
            raise TransientError(str(e)) from e
        except openai.APIStatusError as e:
            if _is_transient_code(e.status_code):
                raise TransientError(str(e), retry_after=_retry_after(e.response)) from e
            raise ProviderError(str(e)) from e
        except openai.APIError as e:
            raise ProviderError(str(e)) from e
        return parse_response(raw)


def _retry_after(response) -> float | None:
    """Retry-After in seconds. The HTTP-date form is ignored (None): rare, and backoff covers it."""
    try:
        value = float(response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if value >= 0 else None


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
        tool_calls=tuple(calls),
        usage=usage,
        stop_reason=choice.finish_reason or "unknown",
        cost_usd=cost,
        served_by=(raw.model_extra or {}).get("provider"),  # OpenRouter: which backend served it
        extra=extra,
        raw=raw,
    )
