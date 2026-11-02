"""What every provider adapter returns, whatever the wire format."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from whippletree.errors import WhippletreeError


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as the model sent it


@dataclass(frozen=True)
class Usage:
    input: int = 0
    output: int = 0
    cached: int = 0

    @property
    def total(self) -> int:
        # cached is already counted inside input (OpenAI/OpenRouter), so it is excluded on purpose
        return self.input + self.output


@dataclass(frozen=True)
class Response:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str
    cost_usd: float | None = None
    served_by: str | None = None
    extra: dict = field(default_factory=dict)  # provider fields to echo back on the next turn
    raw: Any = field(default=None, repr=False)


class ProviderError(Exception):
    """The call failed and retrying won't help (or retries ran out)."""


class TransientError(Exception):
    """Rate limit, server error, or network failure: worth retrying."""


class Provider(Protocol):
    def complete(
        self, messages: list[dict], tools: list[dict], model: str, settings: dict
    ) -> Response: ...


def parse_model(spec: str) -> tuple[str, str]:
    """'ollama:llama3.1:8b' -> ('ollama', 'llama3.1:8b'). Splits on the first colon."""
    provider, sep, model = spec.partition(":")
    if not sep or not provider or not model:
        raise WhippletreeError(f"model must look like provider:model-id, got {spec!r}")
    return provider, model
