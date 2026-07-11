"""Trusted Warcraft text-object source names and deterministic matching."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Final

from .map_archive_reader import MapArchiveReader


class TextObjectSourceKind(StrEnum):
    FUNC = "func"
    STRINGS = "strings"
    ANONYMOUS = "anonymous"


_TRUSTED_NAME: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\\/])(?:[a-z]+)?(?:unit|item|ability|upgrade)(func|strings)\.txt$",
    re.IGNORECASE,
)
_RACES: Final[tuple[str, ...]] = ("Human", "Orc", "Undead", "NightElf", "Neutral")
_TRUSTED_REFERENCE_NAMES: Final[tuple[str, ...]] = (
    "units\\itemfunc.txt",
    "units\\itemstrings.txt",
    "units\\campaignunitfunc.txt",
    "units\\campaignunitstrings.txt",
    "Units\\HumanUnitFunc.txt",
    "Units\\HumanUnitStrings.txt",
    "units\\campaignabilityfunc.txt",
    "units\\campaignabilitystrings.txt",
    "Units\\HumanAbilityFunc.txt",
    "Units\\HumanAbilityStrings.txt",
    "Units\\CampaignUpgradeFunc.txt",
    "Units\\campaignupgradestrings.txt",
    "Units\\HumanUpgradeFunc.txt",
    "Units\\HumanUpgradeStrings.txt",
    "Units\\NeutralUpgradeFunc.txt",
    "Units\\NeutralUpgradeStrings.txt",
) + tuple(
    f"Units\\{race}{object_type}{source}.txt"
    for race in _RACES
    for object_type in ("Unit", "Ability", "Upgrade")
    for source in ("Func", "Strings")
)


def trusted_names(
    archive: MapArchiveReader,
    known_names: Sequence[str],
) -> tuple[str, ...]:
    """Return unique trusted names in deterministic normalized order."""
    candidates: dict[str, str] = {}
    for name in _TRUSTED_REFERENCE_NAMES:
        _add_candidate(candidates, name)
    for name in (*known_names, *archive.list_files()):
        if trusted_source_kind(name) is not None:
            _add_candidate(candidates, name)
    return tuple(sorted(candidates.values(), key=source_name_key))


def trusted_source_kind(name: str) -> TextObjectSourceKind | None:
    """Classify a trusted path as Func or Strings."""
    match = _TRUSTED_NAME.search(name)
    if match is None:
        return None
    return TextObjectSourceKind.FUNC if match.group(1).casefold() == "func" else TextObjectSourceKind.STRINGS


def normalized_name(name: str) -> str:
    return name.replace("/", "\\").casefold()


def source_name_key(name: str) -> tuple[str, str]:
    return normalized_name(name), name


def _add_candidate(candidates: dict[str, str], name: str) -> None:
    normalized = normalized_name(name)
    previous = candidates.get(normalized)
    if previous is None or source_name_key(name) < source_name_key(previous):
        candidates[normalized] = name
