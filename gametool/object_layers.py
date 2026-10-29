"""Known binary object layers, their field precedence and WTS scope."""

from __future__ import annotations

from typing import Final

from .fields import label_for

OBJECT_EXTS: Final = ("w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h")


def binary_object_members(prefix: str) -> tuple[str, ...]:
    """Enumerate both complete object layers, without relying on a listfile."""
    return tuple(
        f"{stem}.{ext}" for stem in (prefix, prefix + "Skin") for ext in OBJECT_EXTS
    )


def binary_layer_priority(source: str) -> int:
    """Campaign fields precede chapter fields; each Skin layer follows its base.

    The source may be bound to an outer campaign using ``archive!member``.
    Priorities remain between Func (30) and localized Strings (50), preserving
    the existing independent text-source policy.
    """
    member = source.rsplit("!", 1)[-1].casefold()
    stem, _, ext = member.rpartition(".")
    if ext not in OBJECT_EXTS:
        return 40
    return {
        "war3campaign": 32,
        "war3campaignskin": 35,
        "war3map": 40,
        "war3mapskin": 45,
    }.get(stem, 40)


def binary_wts_member(source: str) -> str:
    """Both binary layers resolve strings from the same map/campaign WTS."""
    scope, separator, member = source.rpartition("!")
    stem, _, _ext = member.rpartition(".")
    if stem.casefold().endswith("skin"):
        stem = stem[:-4]
    return f"{scope}{separator}{stem}.wts"


def binary_field_key(field_id: str, level: int, data_pointer: int = 0) -> str:
    """Keep the encoded level and data column as independent field identities."""
    key = f"{field_id}:{level}" if level else field_id
    return f"{key}:column:{data_pointer}" if data_pointer else key


def binary_field_label(field_id: str, level: int, data_pointer: int = 0) -> str:
    label = label_for(field_id)
    if level:
        label += f" (等级{level})"
    if data_pointer:
        label += f" (数据列{data_pointer})"
    return label


def split_field_column(key: str) -> tuple[str, str | None]:
    """Separate only an explicit encoded data column; it is never a level.

    Keep decimal spelling as text so query tables can retain arbitrarily long
    evidence without an integer conversion quota.
    """
    base, separator, column = key.rpartition(":column:")
    digits = column[1:] if column.startswith(("-", "+")) else column
    if separator and digits and digits.isascii() and digits.isdecimal():
        return base, column
    return key, None
