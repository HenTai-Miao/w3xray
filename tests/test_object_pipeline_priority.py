"""Cross-format field identity and deterministic priority regressions."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

from w3xtool.fields import label_for
from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
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
        _candidate(
            "HP", slk_col_label("HP"), "1000", "UnitBalance.slk", ObjectSourceKind.SLK
        ),
        _candidate(
            "uhpm", label_for("uhpm"), "2500", "war3map.w3u", ObjectSourceKind.BINARY
        ),
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
        "uhpm",
        label_for("uhpm"),
        "2500",
        "Units\\UnitData.slk",
        ObjectSourceKind.BINARY,
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
    strings = _candidate(
        "HP", "生命", "1800", "UnitStrings.txt", ObjectSourceKind.TEXT_STRINGS
    )
    slk = _candidate("HP", "生命", "1000", "UnitBalance.slk", ObjectSourceKind.SLK)

    # When: source priority is applied.
    merged = merge_object_candidates((strings, slk), {})[0]

    # Then: Strings does not win outside display fields.
    assert merged.fields == [("生命", "1000")]
    assert merged.field_sources == {"HP": "UnitBalance.slk"}


def test_distinct_raw_fields_with_the_same_label_are_preserved() -> None:
    # Given: two real ability fields share one generated presentation label.
    first = _candidate(
        "Adm2", label_for("Adm2"), "11", "war3map.w3a", ObjectSourceKind.BINARY
    )
    second = _candidate(
        "Ams1", label_for("Ams1"), "22", "war3map.w3a", ObjectSourceKind.BINARY
    )

    # When: both fields are materialized.
    merged = merge_object_candidates((first, second), {})[0]

    # Then: raw-field identity prevents either value from being discarded.
    assert merged.field_values["Adm2"] == "11"
    assert merged.field_values["Ams1"] == "22"
    assert merged.fields.count(("召唤单位伤害", "11")) == 1
    assert merged.fields.count(("召唤单位伤害", "22")) == 1


def test_explicit_field_still_replaces_matching_inherited_base_label() -> None:
    # Given: an explicit binary field and an inherited base field share a label.
    binary = _candidate(
        "uhpm", label_for("uhpm"), "2500", "war3map.w3u", ObjectSourceKind.BINARY
    )

    # When: the custom object inherits its base.
    merged = merge_object_candidates(
        (binary,),
        {"hfoo": ("单位", [("生命上限", "420")])},
    )[0]

    # Then: the explicit value replaces, rather than duplicates, the base value.
    assert merged.fields == [("生命上限", "2500")]
    assert merged.field_values == {"uhpm": "2500"}


def test_materialization_retains_equal_priority_field_conflicts() -> None:
    # Given: two binary sources disagree on the same relation-bearing field.
    first = _candidate(
        "Sellitems", "售出物品", "I001", "first.w3u", ObjectSourceKind.BINARY
    )
    second = _candidate(
        "Sellitems", "售出物品", "I002", "second.w3u", ObjectSourceKind.BINARY
    )

    # When: the public object is materialized.
    merged = merge_object_candidates((first, second), {})[0]

    # Then: both same-tier variants remain available as immutable evidence.
    assert {row.value for row in merged.field_evidence} == {"I001", "I002"}


def test_field_evidence_priority_matches_non_display_selection() -> None:
    # Given: Strings and SLK disagree on a non-display shop field.
    strings = _candidate(
        "Sellitems",
        "售出物品",
        "I001",
        "UnitStrings.txt",
        ObjectSourceKind.TEXT_STRINGS,
    )
    slk = _candidate(
        "Sellitems",
        "售出物品",
        "I002",
        "UnitData.slk",
        ObjectSourceKind.SLK,
    )

    # When: public selection and retained evidence are materialized together.
    merged = merge_object_candidates((strings, slk), {})[0]
    priorities = {row.value: row.source_priority for row in merged.field_evidence}

    # Then: evidence priority selects the same winning tier as the public field.
    assert merged.field_values["Sellitems"] == "I002"
    assert priorities["I002"] > priorities["I001"]


def test_field_evidence_order_covers_every_equality_field_across_hash_seeds() -> None:
    # Given: three tied pairs differ only by type, raw value, or WTS source.
    script = textwrap.dedent(
        """\
        from w3xtool.object_candidates import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
        from w3xtool.object_pipeline import merge_object_candidates

        def field(value, value_type, raw_value, value_source):
            return ObjectFieldValue(
                "Sellitems", "售出物品", value, "war3map.w3u",
                ObjectSourceKind.BINARY, value_source, value_type, raw_value,
            )

        fields = (
            field("I001", "beta", "TRIGSTR_1", "war3map.wts#STRING 1"),
            field("I001", "alpha", "TRIGSTR_1", "war3map.wts#STRING 1"),
            field("I002", "string", "TRIGSTR_2", "war3map.wts#STRING 2"),
            field("I002", "string", "TRIGSTR_1", "war3map.wts#STRING 2"),
            field("I003", "string", "TRIGSTR_3", "war3map.wts#STRING 2"),
            field("I003", "string", "TRIGSTR_3", "war3map.wts#STRING 1"),
        )
        candidate = ObjectCandidate("单位", "H001", "hfoo", True, "w3u", fields, ())
        rows = merge_object_candidates((candidate,), {})[0].field_evidence
        print(tuple(
            (row.value, row.value_type, row.raw_value, row.value_source)
            for row in rows
        ))
        """
    )
    expected = (
        "(('I001', 'alpha', 'TRIGSTR_1', 'war3map.wts#STRING 1'), "
        "('I001', 'beta', 'TRIGSTR_1', 'war3map.wts#STRING 1'), "
        "('I002', 'string', 'TRIGSTR_1', 'war3map.wts#STRING 2'), "
        "('I002', 'string', 'TRIGSTR_2', 'war3map.wts#STRING 2'), "
        "('I003', 'string', 'TRIGSTR_3', 'war3map.wts#STRING 1'), "
        "('I003', 'string', 'TRIGSTR_3', 'war3map.wts#STRING 2'))\n"
    )

    # When: identical materialization runs under two distinct hash seeds.
    outputs = tuple(
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=Path(__file__).parent.parent,
            env=os.environ | {"PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "3")
    )

    # Then: every equality field participates in one seed-independent order.
    assert outputs == (expected, expected)
