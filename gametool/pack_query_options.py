"""Immutable request data shared by pack-query interfaces."""

from __future__ import annotations

from dataclasses import dataclass


EMPTY_QUERY_COMMANDS = frozenset(
    {
        "affixes",
        "again",
        "registered",
        "list",
        "buffs",
        "heroes",
        "stats",
        "synth",
        "skills",
        "units",
        "quest",
        "item",
        "tech",
        "price",
        "cmd",
        "calls",
        "shop",
        "text",
        "refs",
    }
)


def query_limit_error(limit: object) -> str:
    """Validate the caller's explicit record count without any numeric ceiling."""
    return (
        "显式 --limit 必须是非负整数；0 表示全量。"
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
        else ""
    )


def parse_query_limit(text: str) -> int:
    """CLI spellings for full coverage normalize to the existing zero contract."""
    if text.strip().casefold() in {"all", "全部"}:
        return 0
    try:
        limit = int(text)
    except ValueError as exc:
        raise ValueError("--limit 需要非负整数或 all/全部 (0=全量)") from exc
    note = query_limit_error(limit)
    if note:
        raise ValueError(note)
    return limit


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
