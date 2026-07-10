"""Cross-format field identity and deterministic priority regressions."""

from __future__ import annotations

from w3xtool.fields import label_for
from w3xtool.object_candidates import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
from w3xtool.object_pipeline import merge_object_candidates
from w3xtool.slk_objects import slk_col_label


def _candidate(
    key: str,
    label: str,
    value: str,
    source: str,
    source_kind: ObjectSourceKind,
) -> ObjectCandidate:
    return ObjectCandidate(
        category="单位",
        obj_id="H001",
        base_id="hfoo",
        is_custom=True,
        ext="slk" if source_kind is ObjectSourceKind.SLK else "w3u",
        fields=(ObjectFieldValue(key, label, value, source, source_kind),),
        refs=(),
    )


def test_real_slk_hp_and_binary_uhpm_compete_as_one_field() -> None:
    # Given: real source keys whose presentation labels differ.
    candidates = (
        _candidate("HP", slk_col_label("HP"), "1000", "UnitBalance.slk", ObjectSourceKind.SLK),
        _candidate("uhpm", label_for("uhpm"), "2500", "war3map.w3u", ObjectSourceKind.BINARY),
    )

    # When: the cross-format candidates are merged.
    merged = merge_object_candidates(candidates, {})[0]

    # Then: binary wins one semantic health field instead of leaving two labels.
    assert merged.fields == [("生命上限", "2500")]
    assert merged.field_values == {"uhpm": "2500"}
    assert merged.field_sources == {"uhpm": "war3map.w3u"}


def test_equal_priority_source_case_ties_are_order_independent() -> None:
    # Given: semantically identical fields whose source paths differ only by case.
    upper = _candidate(
        "uhpm", label_for("uhpm"), "2500", "Units\\UnitData.slk", ObjectSourceKind.BINARY
    )
    lower = _candidate(
        "uhpm", label_for("uhpm"), "2500", "units/unitdata.slk", ObjectSourceKind.BINARY
    )

    # When: candidates arrive in opposite orders.
    forward = merge_object_candidates((upper, lower), {})[0]
    reverse = merge_object_candidates((lower, upper), {})[0]

    # Then: both values and provenance are identical.
    assert forward.fields == reverse.fields
    assert forward.field_values == reverse.field_values
    assert forward.field_sources == reverse.field_sources


def test_strings_non_display_does_not_override_slk() -> None:
    # Given: Strings and SLK collide on the same non-display field.
    strings = _candidate("HP", "生命", "1800", "UnitStrings.txt", ObjectSourceKind.TEXT_STRINGS)
    slk = _candidate("HP", "生命", "1000", "UnitBalance.slk", ObjectSourceKind.SLK)

    # When: source priority is applied.
    merged = merge_object_candidates((strings, slk), {})[0]

    # Then: Strings does not win outside display fields.
    assert merged.fields == [("生命", "1000")]
    assert merged.field_sources == {"HP": "UnitBalance.slk"}
