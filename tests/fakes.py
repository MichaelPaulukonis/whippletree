"""Scripted stand-ins for real providers."""

import json

from whippletree.providers.base import Response, ToolCall, Usage


class FakeProvider:
    """Returns (or raises) the scripted items in order; records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def complete(self, messages, tools, model, settings):
        self.seen.append([dict(m) for m in messages])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(text="", calls=(), inp=10, out=5, cost=None, served_by=None, stop=None, extra=None):
    return Response(
        text=text,
        tool_calls=list(calls),
        usage=Usage(input=inp, output=out),
        stop_reason=stop or ("tool_calls" if calls else "stop"),
        cost_usd=cost,
        served_by=served_by,
        extra=extra or {},
    )


def call(name, args, id="c1"):
    return ToolCall(id=id, name=name, arguments=json.dumps(args))
