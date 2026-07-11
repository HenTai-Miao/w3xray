"""Separate campaign decompression attempts from retained child memory."""

from __future__ import annotations

from typing import final

from .extraction_diagnostics import DiagnosticTarget, record_component_parse_issue


@final
class CampaignByteBudget:
    """Track mutable read and retention totals for one campaign load."""

    __slots__ = ("_read_bytes", "_read_limit", "_retained_bytes", "_retained_limit")

    def __init__(self, retained_limit: int, read_limit: int) -> None:
        self._retained_limit = retained_limit
        self._read_limit = read_limit
        self._retained_bytes = 0
        self._read_bytes = 0

    @property
    def remaining(self) -> int:
        """Return bytes allowed by both independent limits."""
        return min(
            self._retained_limit - self._retained_bytes,
            self._read_limit - self._read_bytes,
        )

    def reserve_read(self, declared_size: int | None) -> int | None:
        """Reserve one read attempt or return ``None`` when no budget remains."""
        reserved = max(1, declared_size or 0)
        if reserved > self.remaining:
            return None
        self._read_bytes += reserved
        return reserved

    def reconcile_read(self, reserved: int, actual_size: int) -> None:
        """Charge only actual bytes beyond the non-refundable reservation."""
        self._read_bytes += max(0, actual_size - reserved)

    def charge_retained(self, size: int) -> None:
        self._retained_bytes += size


def record_campaign_budget_issue(md: DiagnosticTarget, source: str) -> None:
    """Record one consistent recoverable aggregate-budget rejection."""
    record_component_parse_issue(
        md,
        "campaign-child",
        source,
        "campaign child exceeds remaining read/retained byte budget",
        stage="read",
    )
