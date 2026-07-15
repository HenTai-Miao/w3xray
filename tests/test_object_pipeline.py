"""Archive-to-object pipeline integration contracts."""

from __future__ import annotations

import struct

from w3xtool.map_data import GameObject, MapData
from w3xtool.object_pipeline import (
    build_object_identity_index,
    load_object_pipeline,
)


def test_exact_identity_index_keeps_same_rawcode_in_two_categories() -> None:
    # Given: two object kinds legitimately reuse one rawcode.
    unit = GameObject("单位", "w3u", "X001", "hfoo", "同码单位", True)
    item = GameObject("物品", "w3t", "X001", "rat9", "同码物品", True)

    # When/Then: category-aware lookup preserves both exact identities.
    assert build_object_identity_index((unit, item)) == {
        ("单位", "X001"): unit,
        ("物品", "X001"): item,
    }


class FakeArchive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.path = "fixture.w3x"
        self._data = b""
        self._files = {
            self._normalize(name): (name, value) for name, value in files.items()
        }

    def has_file(self, name: str) -> bool:
        return self._normalize(name) in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[self._normalize(name)][1]

    def list_files(self) -> list[str]:
        return [name for name, _value in self._files.values()]

    def close(self) -> None:
        return None

    @staticmethod
    def _normalize(name: str) -> str:
        return name.replace("/", "\\").casefold()


def _slk(
    columns: tuple[str, ...], rows: tuple[tuple[str, dict[str, str]], ...]
) -> bytes:
    lines = ["ID;P", f"B;X{len(columns)};Y{len(rows) + 1}"]
    for x, column in enumerate(columns, 1):
        lines.append(f'C;X{x};Y1;K"{column}"')
    for y, (code, values) in enumerate(rows, 2):
        lines.append(f'C;X1;Y{y};K"{code}"')
        for x, column in enumerate(columns, 1):
            if column in values:
                lines.append(f'C;X{x};Y{y};K"{values[column]}"')
    lines.append("E")
    return "\n".join(lines).encode("latin-1")


def _binary_object(
    old_id: str, new_id: str, values: tuple[tuple[str, str], ...]
) -> bytes:
    mods = b"".join(
        field_id.encode("latin-1")
        + struct.pack("<i", 3)
        + value.encode("utf-8")
        + b"\x00"
        + struct.pack("<I", 0)
        for field_id, value in values
    )
    obj = (
        old_id.encode("latin-1")
        + new_id.encode("latin-1")
        + struct.pack("<i", len(values))
        + mods
    )
    return struct.pack("<ii", 2, 0) + struct.pack("<i", 1) + obj


def test_binary_and_slk_coexist_in_pipeline_without_duplicate_codes() -> None:
    # Given: binary, text and SLK all describe the same custom object.
    archive = FakeArchive(
        {
            "war3map.w3u": _binary_object(
                "hfoo", "H001", (("unam", "Binary Footman"),)
            ),
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=Localized Footman\n",
            "Units\\UnitData.slk": _slk(
                ("unitID", "Name", "race"),
                (("H001", {"Name": "SLK Footman", "race": "human"}),),
            ),
        }
    )
    md = MapData(path="fixture.w3x", name="fixture")

    # When: one deterministic pipeline assembles the category.
    load_object_pipeline(md, archive, {}, base_objects={})

    # Then: one rawcode remains, text supplies display, and SLK supplies missing data.
    codes = [obj.obj_id for values in md.objects.values() for obj in values]
    assert codes == ["H001"]
    assert list(md.obj_index) == ["H001"]
    assert md.obj_index["H001"].name == "Localized Footman"
    assert dict(md.obj_index["H001"].fields)["种族"] == "human"
    assert md.obj_index["H001"].ext == "w3u"


def test_load_map_impl_merges_map_and_campaign_candidates_once() -> None:
    # Given: text, binary, SLK, and campaign sources have distinct WTS scopes.
    from w3xtool import api
    from w3xtool.load_context import MapLoadContext

    archive = FakeArchive(
        {
            "war3map.wts": "STRING 1\n{\n地图文本单位\n}\n".encode(),
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=TRIGSTR_1\n",
            "war3map.w3u": _binary_object(
                "hfoo", "H002", (("uhpm", "2500"), ("uabi", "A001"))
            ),
            "Units\\UnitData.slk": _slk(
                ("unitID", "race", "abilList"),
                (("H002", {"race": "human", "abilList": "A002"}),),
            ),
            "war3campaign.wts": "STRING 1\n{\n战役共享单位\n}\n".encode(),
            "war3campaign.w3u": _binary_object(
                "hfoo", "H003", (("unam", "TRIGSTR_1"),)
            ),
        }
    )

    # When: the high-level loader collects both namespaces before one materialization.
    md = api._load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: every source survives without aliases or category-wide suppression.
    assert {"H001", "H002", "H003"}.issubset(md.obj_index)
    assert md.obj_index["H001"].name == "地图文本单位"
    assert md.obj_index["H003"].name == "战役共享单位"
    h002 = md.obj_index["H002"]
    assert dict(h002.fields)["生命上限"] == "2500"
    assert dict(h002.fields)["种族"] == "human"
    assert ("uabi", ["A001"]) in h002.ref_fields
    assert ("abilList", ["A002"]) in h002.ref_fields
    rawcodes = [item.obj_id for bucket in md.objects.values() for item in bucket]
    assert len(rawcodes) == len(set(rawcodes))
    assert all(code == item.obj_id for code, item in md.obj_index.items())
    assert md.obj_index["hfoo"].obj_id == "hfoo"
    assert md.obj_index["hfoo"] is not h002
