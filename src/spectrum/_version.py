"""Single source of truth for the package version."""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("spectrum-os")
except Exception:
    __version__ = "0.0.0-dev"
