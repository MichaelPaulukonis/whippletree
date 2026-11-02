"""Load settings from a dict-like source."""


def get_port(settings, default=8080):
    value = settings.get("port")
    if value is None:
        return default
    return int(value)


def get_host(settings):
    return settings.get("host", "localhost")
