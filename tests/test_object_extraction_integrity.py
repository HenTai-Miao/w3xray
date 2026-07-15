"""Lossless object extraction and knowledge-pack field coverage."""

from __future__ import annotations

from pathlib import Path

from w3xtool.api import GameObject, MapData
from w3xtool.knowledge_pack import write_knowledge_pack
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_materialization import merge_object_candidates
import w3xtool.object_candidates as object_candidates


def test_explicit_empty_object_field_overrides_inherited_value() -> None:
    # Given: a map explicitly clears a tooltip inherited from its base object.
    empty_tip = ObjectFieldValue(
        "utip", "\u63d0\u793a", "", "war3map.w3u", ObjectSourceKind.BINARY
    )
    candidate = ObjectCandidate(
        "\u5355\u4f4d", "H001", "hfoo", True, "w3u", (empty_tip,), ()
    )

    # When: the final object is materialized.
    (obj,) = merge_object_candidates(
        (candidate,), {"hfoo": ("\u5355\u4f4d", (("\u63d0\u793a", "base tip"),))}
    )

    # Then: the explicit clear is retained and the inherited text does not leak back in.
    assert obj.field_values["utip"] == ""
    assert "base tip" not in dict(obj.fields).values()


def test_float_object_value_keeps_more_than_four_significant_digits() -> None:
    # Given: a representable object value whose important digits exceed .4g.
    # When: the extraction boundary formats it for the public model.
    rendered = object_candidates._resolved_value(1234.56, {})

    # Then: presentation rounding does not destroy the extracted value.
    assert rendered == "1234.56"


def test_knowledge_pack_exports_every_object_field_with_source(tmp_path: Path) -> None:
    # Given: an object has display and technical fields from different sources.
    obj = GameObject(
        category="\u5355\u4f4d",
        ext="w3u",
        obj_id="H001",
        base_id="hfoo",
        name="\u81ea\u5b9a\u4e49\u6b65\u5175",
        is_custom=True,
        fields=[
            ("\u8bf4\u660e", "\u5730\u56fe\u8bf4\u660e"),
            ("\u751f\u547d\u4e0a\u9650", "2500"),
            ("\u79fb\u52a8\u901f\u5ea6", "300"),
        ],
        field_values={
            "display:description": "\u5730\u56fe\u8bf4\u660e",
            "uhpm": "2500",
            "umvs": "300",
        },
        field_sources={
            "display:description": "Units\\HumanUnitStrings.txt",
            "uhpm": "war3map.w3u",
            "umvs": "UnitData.slk",
        },
    )
    md = MapData(
        path="fixture.w3x",
        name="\u5b8c\u6574\u5b57\u6bb5",
        objects={"\u5355\u4f4d": [obj]},
    )

    # When: the consolidated knowledge pack is exported.
    _ = write_knowledge_pack(md, str(tmp_path))

    # Then: technical values and provenance have a complete structured artifact.
    text = (tmp_path / "\u5bf9\u8c61\u5b57\u6bb5.tsv").read_text(encoding="utf-8")
    assert (
        "\u5206\u7c7b\tID\t\u540d\u79f0\t\u5b57\u6bb5\u952e\t\u5b57\u6bb5\u540d\t\u503c\t\u6765\u6e90"
        in text
    )
    assert "uhpm\t\u751f\u547d\u4e0a\u9650\t2500\twar3map.w3u" in text
    assert "umvs\t\u79fb\u52a8\u901f\u5ea6\t300\tUnitData.slk" in text
    manifest = (tmp_path / "\u8d44\u6599\u5305\u76ee\u5f55.tsv").read_text(
        encoding="utf-8"
    )
    assert "\u5bf9\u8c61\t\u5bf9\u8c61\u5b57\u6bb5.tsv" in manifest
