"""Identity-level regression tests for real-map text acceptance."""

from __future__ import annotations

import pytest

from tests.real_map_text_acceptance import TsvTable, missing_legacy_text

_LEGACY_HEADER = (
    "分类",
    "对象ID",
    "等级",
    "原始提示",
    "原始说明",
)
_COMPLETE_HEADER = (
    "分类",
    "对象ID",
    "文本角色",
    "等级/变体",
    "原始全文",
)


def test_same_text_on_another_object_does_not_hide_missing_legacy_evidence() -> None:
    # Given: I001's legacy tip appears only on a different v2 object.
    old = TsvTable(_LEGACY_HEADER, (("物品", "I001", "", "相同文本", ""),))
    new = TsvTable(
        _COMPLETE_HEADER,
        (("物品", "I002", "基础提示", "", "相同文本"),),
    )

    # When: legacy preservation is checked for one map digest.
    missing = missing_legacy_text("a" * 64, old, new)

    # Then: the original object's identity is reported as missing.
    assert missing == ("aaaaaaaa:物品:I001:无等级:基础提示",)


@pytest.mark.parametrize(
    "new_row",
    (
        ("单位", "I001", "基础提示", "1", "相同文本"),
        ("物品", "I001", "学习提示", "1", "相同文本"),
        ("物品", "I001", "基础提示", "2", "相同文本"),
    ),
)
def test_category_role_or_numeric_level_mismatch_cannot_satisfy_identity(
    new_row: tuple[str, ...],
) -> None:
    # Given: the text matches but one identity component does not.
    old = TsvTable(_LEGACY_HEADER, (("物品", "I001", "1", "相同文本", ""),))
    new = TsvTable(_COMPLETE_HEADER, (new_row,))

    # When: preservation is checked for the old identity.
    missing = missing_legacy_text("1" * 64, old, new)

    # Then: category, role, and numeric level are each mandatory.
    assert missing == ("11111111:物品:I001:1:基础提示",)


def test_item_editor_description_satisfies_legacy_description_at_object_level() -> None:
    # Given: the legacy item row repeated an unlevelled ides value at level 3.
    old = TsvTable(_LEGACY_HEADER, (("物品", "I001", "3", "", "编辑说明"),))
    new = TsvTable(
        _COMPLETE_HEADER,
        (("物品", "I001", "编辑器描述", "", "编辑说明"),),
    )

    # When: legacy preservation resolves the old description role.
    missing = missing_legacy_text("b" * 64, old, new)

    # Then: the same item's unlevelled editor description is accepted.
    assert missing == ()


def test_technology_level_one_fields_match_legacy_unlevelled_rows() -> None:
    # Given: legacy gtp1/gub1 fields were emitted without an explicit level.
    old = TsvTable(
        _LEGACY_HEADER,
        (("科技", "R001", "", "一级提示", "一级说明"),),
    )
    new = TsvTable(
        _COMPLETE_HEADER,
        (
            ("科技", "R001", "基础提示", "1", "一级提示"),
            ("科技", "R001", "扩展提示", "1", "一级说明"),
        ),
    )

    # When: legacy preservation compares semantic levels.
    missing = missing_legacy_text("c" * 64, old, new)

    # Then: Warcraft's implicit first technology level is accepted.
    assert missing == ()


def test_buff_columns_map_to_explicit_buff_text_roles() -> None:
    # Given: a legacy buff row used the generic tip and description columns.
    old = TsvTable(
        _LEGACY_HEADER,
        (("增益", "B001", "", "增益提示", "增益说明"),),
    )
    new = TsvTable(
        _COMPLETE_HEADER,
        (
            ("增益", "B001", "Buff提示", "", "增益提示"),
            ("增益", "B001", "Buff扩展提示", "", "增益说明"),
        ),
    )

    # When: the legacy columns are mapped to semantic v2 roles.
    missing = missing_legacy_text("d" * 64, old, new)

    # Then: the same buff identity retains both values.
    assert missing == ()


def test_unlevelled_fallback_matches_legacy_rows_repeated_per_level() -> None:
    # Given: the legacy selector repeated a base ability value at level 4.
    old = TsvTable(
        _LEGACY_HEADER,
        (("技能", "A001", "4", "通用提示", "通用说明"),),
    )
    new = TsvTable(
        _COMPLETE_HEADER,
        (
            ("技能", "A001", "基础提示", "", "通用提示"),
            ("技能", "A001", "扩展提示", "", "通用说明"),
        ),
    )

    # When: identity-level preservation checks the legacy fallback row.
    missing = missing_legacy_text("e" * 64, old, new)

    # Then: the same object's unlevelled roles satisfy the repeated values.
    assert missing == ()


def test_legacy_description_fallback_maps_to_same_object_editor_role() -> None:
    # Given: an old unit description came from display:description fallback.
    old = TsvTable(
        _LEGACY_HEADER,
        (("单位", "n001", "", "", "建筑说明"),),
    )
    new = TsvTable(
        _COMPLETE_HEADER,
        (("单位", "n001", "编辑器描述", "", "建筑说明"),),
    )

    # When: the legacy fallback is compared by object and semantic role.
    missing = missing_legacy_text("f" * 64, old, new)

    # Then: its editor-description evidence satisfies the old description.
    assert missing == ()
