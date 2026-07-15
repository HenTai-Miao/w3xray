"""Deterministic thread handle used by GUI worker integration tests."""

from __future__ import annotations

from collections.abc import Callable


class InlineGuiThread:
    def __init__(
        self,
        *,
        target: Callable[[], None],
        daemon: bool,
        name: str,
    ) -> None:
        self._target = target
        self.daemon = daemon
        self.name = name

    def start(self) -> None:
        self._target()

    def join(self, timeout: float | None = None) -> None:
        _ = timeout

    def is_alive(self) -> bool:
        return False


__all__ = ("InlineGuiThread",)
