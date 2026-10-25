"""Immutable request data shared by pack-query interfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PackQueryCliOptions:
    """A query request; zero limit preserves the complete result."""

    pack_dir: str
    command: str
    query: str
    limit: int = 0
    pack_dir_b: str = ""
    as_json: bool = False
    near_kind: str = ""
