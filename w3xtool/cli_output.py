"""Deterministic UTF-8 output for source and packaged CLI entrypoints."""

from __future__ import annotations

import sys
from typing import Protocol, runtime_checkable


@runtime_checkable
class _ReconfigurableTextStream(Protocol):
    def reconfigure(
        self,
        *,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> None: ...


def configure_cli_output() -> None:
    """Make redirected and console output independent of the Windows ACP."""
    for stream in (sys.stdout, sys.stderr):
        if not isinstance(stream, _ReconfigurableTextStream):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            continue
