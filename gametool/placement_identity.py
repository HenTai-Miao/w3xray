"""Category-qualified physical placement identities shared by exports and relations."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain

from .map_data import GameObject, MapData
from .base_catalog import english_name_for, fine_category_for
from .base_names import BASE_NAMES
from .base_objects import BASE_OBJECTS


@dataclass(frozen=True, slots=True)
class PlacementIdentity:
    name: str
    category: str
    english: str = ""
    fine: str = ""
    diagnostic: str = ""
    candidates: tuple[str, ...] = ()


class PlacementObjectIndex:
    """One read-only category index per operation, including legacy builder inputs."""

    def __init__(self, md: MapData) -> None:
        self.objects: dict[tuple[str, str], GameObject] = {}
        self.categories: dict[str, set[str]] = {}
        for obj in chain(
            chain.from_iterable(md.objects.values()),
            md.obj_identity_index.values(),
            md.obj_index.values(),
        ):
            category = "单位" if obj.category == "英雄" else obj.category
            identity = (category, obj.obj_id)
            previous = self.objects.get(identity)
            if previous is None or previous.ext == "script" and obj.ext != "script":
                self.objects[identity] = obj
            if obj.ext != "script":
                self.categories.setdefault(obj.obj_id, set()).add(category)
        self.names: dict[tuple[str, str], str] = {}
        self.placements: dict[tuple[str, tuple[str, ...]], PlacementIdentity] = {}

    def name(self, category: str, code: str) -> str:
        identity = (category, code)
        if identity not in self.names:
            obj = self.objects.get(identity)
            base = BASE_OBJECTS.get(code)
            if obj is not None and obj.ext != "script":
                self.names[identity] = obj.name or code
            elif base is not None and base[0] == category:
                self.names[identity] = (
                    BASE_NAMES.get(code) or english_name_for(code) or code
                )
            else:
                self.names[identity] = code
        return self.names[identity]

    def placement(self, code: str, allowed: tuple[str, ...]) -> PlacementIdentity:
        key = (code, allowed)
        if key in self.placements:
            return self.placements[key]
        known = set(self.categories.get(code, ()))
        base = BASE_OBJECTS.get(code)
        if base is not None:
            known.add(base[0])
        candidates = [category for category in allowed if category in known]
        if len(candidates) == 1:
            category = candidates[0]
            obj = self.objects.get((category, code))
            bases = (
                (obj.base_id, code)
                if obj is not None and obj.ext != "script"
                else (code,)
            )
            metadata_base = next(
                (
                    base_id
                    for base_id in bases
                    if (record := BASE_OBJECTS.get(base_id)) is not None
                    and record[0] == category
                ),
                "",
            )
            label = PlacementIdentity(
                self.name(category, code),
                category,
                english_name_for(metadata_base),
                fine_category_for(metadata_base),
                candidates=tuple(candidates),
            )
        elif candidates:
            label = PlacementIdentity(
                code,
                "",
                diagnostic="同码放置分类存在歧义，未猜测；候选: "
                + "；".join(
                    f"{category}: {self.name(category, code)}"
                    for category in candidates
                ),
                candidates=tuple(candidates),
            )
        else:
            label = PlacementIdentity(
                code,
                "",
                diagnostic="未找到已确认的"
                + "/".join(allowed)
                + "对象定义；已知分类: "
                + ("、".join(sorted(known)) or "无"),
            )
        self.placements[key] = label
        return label


__all__ = ("PlacementIdentity", "PlacementObjectIndex")
