"""官方秘籍/调试口令残留的只读检测。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .api import MapData

_CHEAT_PHRASES: Final = frozenset({
    "allyourbasearebelongtous",
    "daylightsavings",
    "greedisgood",
    "iocainepowder",
    "iseedeadpeople",
    "itvexesme",
    "keysersoze",
    "leafittome",
    "lightsout",
    "motherland",
    "pointbreak",
    "riseandshine",
    "sharpandshiny",
    "somebodysetusupthebomb",
    "strengthandhonor",
    "synergy",
    "tenthleveltaurenchieftain",
    "thedudeabides",
    "thereisnospoon",
    "warpten",
    "whoisjohngalt",
    "whosyourdaddy",
})
_CHEAT_RE: Final = re.compile(
    r"\b(" + "|".join(sorted(_CHEAT_PHRASES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CheatResidue:
    phrase: str
    source: str
    script: str
    detail: str


@dataclass(frozen=True, slots=True)
class CheatReport:
    items: tuple[CheatResidue, ...]

    @property
    def by_phrase(self) -> dict[str, CheatResidue]:
        return {item.phrase: item for item in self.items}


def build_cheat_report(md: MapData) -> CheatReport:
    """扫描脚本中残留的官方秘籍/调试口令字符串。"""
    from .script_scan import scan_chat_commands

    items: list[CheatResidue] = []
    seen: set[tuple[str, str]] = set()
    for script_name, text in sorted(md.scripts.items()):
        for command in scan_chat_commands(text):
            phrase = _normalize_phrase(command.command)
            if phrase in _CHEAT_PHRASES:
                _append_unique(items, seen, phrase, "聊天指令", script_name, command.command)
        for match in _CHEAT_RE.finditer(text):
            phrase = match.group(1).lower()
            _append_unique(items, seen, phrase, "脚本文本", script_name, match.group(0))
    return CheatReport(tuple(items))


def _normalize_phrase(value: str) -> str:
    return value.strip().lstrip("-/").lower()


def _append_unique(
    items: list[CheatResidue],
    seen: set[tuple[str, str]],
    phrase: str,
    source: str,
    script: str,
    detail: str,
) -> None:
    key = (phrase, script)
    if key in seen:
        return
    seen.add(key)
    items.append(CheatResidue(
        phrase=phrase,
        source=source,
        script=script,
        detail=detail,
    ))
