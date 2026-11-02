"""A tool is a JSON-schema'd function the model can call."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class ToolError(Exception):
    """Bad call from the model. The message goes back to the model as the tool result."""


@dataclass(frozen=True)
class Submit:
    """Returned by a terminal tool on success: the loop stops and returns `value`."""

    value: Any


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[[dict], "str | Submit"]
    terminal: bool = False

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
