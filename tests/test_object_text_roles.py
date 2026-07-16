"""Complete object-text role and immutable-index contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextRecord,
    ObjectTextState,
    TextSelectionReason,
    TextSourcePriority,
    empty_object_text_index,
)
from w3xtool.object_text_roles import TextRoleMatch, classify_text_field


@pytest.mark.parametrize(
    ("key", "label", "semantic_field"),
    (
        ("ResearchArt", "图标 - 学习", "researchart"),
        ("Researchbuttonpos", "按钮位置 - 学习", "researchbuttonpos"),
        ("Researchhotkey", "热键 - 学习", "researchhotkey"),
        ("Orderoff", "关闭命令", "orderoff"),
    ),
)
def test_control_fields_keep_their_own_string_identity(
    key: str,
    label: str,
    semantic_field: str,
) -> None:
    # Given / When: metadata confirms a control field happens to store a string.
    actual = classify_text_field("技能", key, label, "string")

    # Then: tooltip substrings do not steal the field's exact identity.
    assert actual == TextRoleMatch(semantic_field, None, semantic_field)


def test_untip_is_the_only_exact_close_tip_alias() -> None:
    # Given / When: the canonical close-tooltip key is classified.
    actual = classify_text_field("技能", "Untip", "提示工具 - 关闭", "string")

    # Then: its closed alias supplies the precise semantic identity.
    assert actual == TextRoleMatch("关闭提示", None, "untip")


def test_exact_normalized_label_alias_keeps_its_explicit_level() -> None:
    # Given / When: an unknown raw key has one whole closed label alias.
    actual = classify_text_field(
        "技能",
        "CustomText",
        "提示工具 - 学习 - 扩展的 (等级3)",
        "string",
    )

    # Then: normalization removes only the explicit level decoration.
    assert actual == TextRoleMatch("学习扩展提示", 3, "researchubertip")


@pytest.mark.parametrize(
    ("category", "key", "label", "expected"),
    (
        ("单位", "unam", "名称", TextRoleMatch("名称", None, "name")),
        ("单位", "Propernames", "称谓", TextRoleMatch("称谓", None, "propernames")),
        (
            "技能",
            "ansf",
            "编辑器后缀",
            TextRoleMatch("编辑器后缀", None, "editorsuffix"),
        ),
        ("物品", "utip", "提示工具 - 基础", TextRoleMatch("基础提示", None, "tip")),
        (
            "物品",
            "utub",
            "提示工具 - 扩展的",
            TextRoleMatch("扩展提示", None, "ubertip"),
        ),
        (
            "技能",
            "aret",
            "提示工具 - 学习",
            TextRoleMatch("学习提示", None, "researchtip"),
        ),
        (
            "技能",
            "arut:3",
            "提示工具 - 学习 - 扩展的 (等级3)",
            TextRoleMatch("学习扩展提示", 3, "researchubertip"),
        ),
        (
            "技能",
            "aut1:2",
            "提示工具 - 关闭 (等级2)",
            TextRoleMatch("关闭提示", 2, "untip"),
        ),
        (
            "技能",
            "auu1",
            "提示工具 - 关闭 - 扩展的",
            TextRoleMatch("关闭扩展提示", None, "unubertip"),
        ),
        ("增益", "ftip", "工具提示", TextRoleMatch("Buff提示", None, "tip")),
        (
            "增益",
            "fube:4",
            "工具提示 - 扩展的 (等级4)",
            TextRoleMatch("Buff扩展提示", 4, "ubertip"),
        ),
        (
            "单位",
            "ReviveTip",
            "提示工具 - 复活",
            TextRoleMatch("复活提示", None, "revivetip"),
        ),
        (
            "单位",
            "AwakenTip",
            "提示工具 - 唤醒",
            TextRoleMatch("唤醒提示", None, "awakentip"),
        ),
        (
            "物品",
            "ides",
            "描述",
            TextRoleMatch("编辑器描述", None, "editordescription"),
        ),
        (
            "科技",
            "gub3",
            "提示工具 - 扩展的 3",
            TextRoleMatch("扩展提示", 3, "ubertip"),
        ),
    ),
)
def test_classifier_covers_every_requested_role_and_explicit_level(
    category: str,
    key: str,
    label: str,
    expected: TextRoleMatch,
) -> None:
    # Given / When: one known text-bearing object field is classified.
    actual = classify_text_field(category, key, label)

    # Then: its semantic role and level are stable.
    assert actual == expected


def test_embedded_family_digit_is_not_mistaken_for_a_level() -> None:
    # Given / When: the ability tooltip family contains its normal suffix digit.
    actual = classify_text_field("技能", "atp1", "提示工具 - 普通")

    # Then: it is the unlevelled base role, not level one.
    assert actual == TextRoleMatch("基础提示", None, "tip")


def test_non_text_field_is_not_classified_from_an_unrelated_label() -> None:
    # Given / When: a numeric ability field contains no text-role metadata.
    actual = classify_text_field("技能", "acdn:2", "冷却时间 (等级2)")

    # Then: it is not emitted as object text.
    assert actual is None


def test_metadata_confirmed_unknown_string_uses_raw_field_role() -> None:
    # Given / When: metadata marks an otherwise unknown upgrade field as text.
    actual = classify_text_field("科技", "gco1", "效果 1 - %s", "string")

    # Then: the stable raw field key becomes the lossless text role.
    assert actual == TextRoleMatch("gco1", None, "gco1")


def test_text_index_is_immutable_sorted_and_queryable() -> None:
    # Given: records arrive out of order for two objects.
    later = _record("I002", "第二件", 2)
    first = _record("I001", "第一件", 1)

    # When: the immutable index is built.
    index = ObjectTextIndex.build((later, first))

    # Then: stable ordering, object lookup, and frozen values are enforced.
    assert index.records == (first, later)
    assert index.for_object("物品", "I001") == (first,)
    assert index.counts_by_state() == {ObjectTextState.MAP_VALUE: 2}
    with pytest.raises(FrozenInstanceError):
        setattr(first, "raw_value", "changed")


def test_empty_text_index_is_a_reusable_empty_value() -> None:
    # Given / When: two callers request the default index.
    first = empty_object_text_index()
    second = empty_object_text_index()

    # Then: both expose the same empty immutable behavior.
    assert first.records == second.records == ()
    assert first.for_object("物品", "I001") == ()
    assert first.counts_by_state() == {}


def _record(object_id: str, text: str, ordinal: int) -> ObjectTextRecord:
    return ObjectTextRecord(
        category="物品",
        object_id=object_id,
        base_id="ratf",
        object_name=object_id,
        is_custom=True,
        role="扩展提示",
        semantic_field="ubertip",
        field_key="utub",
        field_label="提示文本",
        level=None,
        raw_value=text,
        readable_value=text,
        source_kind="地图二进制",
        source_path="war3map.w3t",
        source_priority=int(TextSourcePriority.MAP_BINARY),
        state=ObjectTextState.MAP_VALUE,
        placeholder=False,
        conflict_group="",
        is_current=True,
        selection_reason=TextSelectionReason.HIGHEST_PRIORITY_VALUE,
        evidence_ordinal=ordinal,
    )
