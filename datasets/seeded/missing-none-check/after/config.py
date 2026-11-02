"""Load settings from a dict-like source."""

import os


def get_port(settings, default=8080):
    value = settings.get("port")
    return int(value)


def get_host(settings):
    return settings.get("host", "localhost")


def get_debug(settings):
    raw = os.environ.get("APP_DEBUG", settings.get("debug", "false"))
    return str(raw).lower() in ("1", "true", "yes")
