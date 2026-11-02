"""Errors for bad usage or setup. The CLI prints these as one line and exits 2."""


class WhippletreeError(Exception):
    """A usage or setup problem the user can fix (bad model spec, no cases, existing trace)."""
