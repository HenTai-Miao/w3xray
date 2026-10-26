"""Item queries retain every linked ability field without guessing runtime effects."""

import csv
from pathlib import Path

import pytest

from gametool import pack_query_cli as queries
from gametool.pack_query_options import PackQueryCliOptions

_HEADER = ["分类", "ID", "名称", "字段键", "字段名", "值", "来源"]


def _write(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")


def _pack(pack: Path, fields: list[list[str]], *, items: int = 1) -> Path:
    _write(
        pack / "对象ID" / "物品.tsv",
        [
            ["分类", "ID", "数值", "基础ID", "名称", "自定义", "说明"],
            *[
                ["物品", f"I{i:03x}", "1", "zzzz", f"装备{i}", "是", "地图物品说明"]
                for i in range(1, items + 1)
            ],
        ],
    )
    path = pack / "对象字段.tsv"
    _write(path, [_HEADER, *fields])
    return path


def _link(value: str = "A001", key: str = "iabi", item: str = "I001") -> list[str]:
    return ["物品", item, "装备", key, "携带技能", value, "map.w3t"]


def _field(
    key: str, value: str, *, code: str = "A001", source: str = "map.w3a"
) -> list[str]:
    return ["技能", code, "关联技能", key, "字段完整名称", value, source]


def _item(pack: Path, query: str = "I001", limit: int = 0):
    return queries.execute_pack_query(
        PackQueryCliOptions(str(pack), "item", query, limit=limit)
    )


@pytest.mark.parametrize(
    "key",
    [
        "Iatt:1",
        "Idef1",
        "Ilif:1",
        "Iman1",
        "Ihpr:1",
        "Imrp1",
        "Imvb:1",
        "Isib1",
        "Isx1:1",
        "Ispi1",
        "Ivam:1",
        "Ixs2:1",
        "DataA1",
        "arbitrary:99999",
        "自定义原文键",
    ],
)
def test_item_displays_every_ability_field_including_unclassified_keys(
    tmp_path: Path, key: str
) -> None:
    path = _pack(tmp_path, [_link(), _field(key, "完整值末尾")])
    before = path.read_bytes()
    result = _item(tmp_path)
    assert (
        result.exit_code == 0
        and key in result.render()
        and "完整值末尾" in result.render()
    )
    assert "map.w3a" in result.render() and "[A001]" in result.render()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "value",
    [
        "-5",
        "+5",
        "-0.000",
        "0",
        "1e-99",
        "1234567890123456789012345678901234567890",
        "0.12345678901234567890123456789012345678901234567890",
    ],
)
def test_attribute_summaries_preserve_signs_and_numeric_spelling(
    tmp_path: Path, value: str
) -> None:
    _pack(tmp_path, [_link(), _field("Istr:1", value)])
    expected = value if value.startswith(("+", "-")) else "+" + value
    assert queries.load_item_equipped_effects(tmp_path) == {
        "I001": [expected + " 力量"]
    }
    assert value in _item(tmp_path).render() and "+-" not in _item(tmp_path).render()


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "-Infinity", "未确定表达式", "", "-", "'", "12 + 13"]
)
def test_unknown_numeric_values_remain_raw_field_evidence(
    tmp_path: Path, value: str
) -> None:
    _pack(tmp_path, [_link(), _field("Istr:1", value)])
    assert queries.load_item_equipped_effects(tmp_path) == {}
    text = _item(tmp_path).render()
    assert "Istr:1" in text and (value in text if value else "显式空值" in text)


@pytest.mark.parametrize("reverse", [False, True])
def test_all_levels_are_retained_and_order_does_not_choose_the_effect(
    tmp_path: Path, reverse: bool
) -> None:
    fields = [
        _field("Istr:2", "22"),
        _field("Istr:1", "11"),
        _field("Istr:30000", "333"),
    ]
    _pack(tmp_path, [_link(), *(list(reversed(fields)) if reverse else fields)])
    effects = queries.load_item_equipped_effects(tmp_path)["I001"]
    assert len(effects) == 3 and all(
        any(value in effect for effect in effects)
        for value in ["+11 力量", "+22 力量", "+333 力量"]
    )
    assert (
        "等级 1" in effects[0] and "等级 2" in effects[1] and "等级 30000" in effects[2]
    )


def test_conflicting_values_for_a_level_are_kept_with_context(tmp_path: Path) -> None:
    _pack(
        tmp_path,
        [_link(), _field("Istr:1", "11"), _field("Istr1", "22", source="other.slk")],
    )
    effects = queries.load_item_equipped_effects(tmp_path)["I001"]
    assert len(effects) == 2 and all(
        "等级 1" in value and "A001" in value for value in effects
    )
    assert "11" in _item(tmp_path).render() and "other.slk" in _item(tmp_path).render()


def test_mirrored_links_and_fields_do_not_duplicate_ability_evidence(
    tmp_path: Path,
) -> None:
    row = _field("Istr:1", "11")
    _pack(
        tmp_path,
        [
            _link("A001, A001"),
            _link("A001, A001"),
            row,
            row,
            _field("Istr1", "11", source="other.slk"),
        ],
    )
    assert queries.load_item_equipped_effects(tmp_path) == {"I001": ["+11 力量"]}
    text = _item(tmp_path).render()
    assert (
        text.count("  关联技能 [A001]") == 1
        and "map.w3a" in text
        and "other.slk" in text
    )


def test_inherited_ability_fields_remain_raw_and_do_not_override_custom_summary(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        [
            _link(),
            _field("Istr:1", "11"),
            _field("base:Istr:1", "1", source="base:AIs1"),
            _field("base:DataC1", "777", source="base:family"),
        ],
    )
    assert queries.load_item_equipped_effects(tmp_path) == {"I001": ["+11 力量"]}
    text = _item(tmp_path).render()
    assert (
        "base:Istr:1" in text
        and "base:DataC1" in text
        and "777" in text
        and "继承" in text
    )


@pytest.mark.parametrize(
    "base_key", ["base:iabi", "base:abilList", "base:技能", "BASE:iabi"]
)
def test_recorded_inherited_skill_links_are_available_without_custom_links(
    tmp_path: Path, base_key: str
) -> None:
    _pack(tmp_path, [_link(key=base_key), _field("Iatt:1", "100")])
    assert "[A001]" in _item(tmp_path).render() and "100" in _item(tmp_path).render()


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_empty_custom_skill_list_overrides_inherited_links(
    tmp_path: Path, reverse: bool
) -> None:
    links = [_link("", key="iabi"), _link("A001", key="base:iabi")]
    _pack(
        tmp_path,
        [*(list(reversed(links)) if reverse else links), _field("Istr:1", "11")],
    )
    assert queries.load_item_equipped_effects(tmp_path) == {}
    text = _item(tmp_path).render()
    assert "显式空值" in text and "覆盖" in text and "  关联技能 [A001]" not in text


def test_missing_skill_fields_and_unparsed_links_have_recovery_paths(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, [_link("A001"), _link("动态变量")])
    text = _item(tmp_path).render()
    assert "动态变量" in text and "字段未记录" in text and "skills A001" in text
    assert "多种取值" in text


def test_multi_line_and_wide_field_values_remain_complete(tmp_path: Path) -> None:
    value = "完整说明\n\t" * 5000 + "最终尾部"
    _pack(tmp_path, [_link(), _field("arbitrary", value), _field("", "无键但有证据")])
    text = _item(tmp_path, limit=1).render()
    assert value in text and "无键但有证据" in text and "字段键未记录" in text


def test_an_explicit_item_limit_keeps_every_field_of_the_selected_skill(
    tmp_path: Path,
) -> None:
    _pack(
        tmp_path,
        [
            _link(),
            _link("A002", item="I002"),
            *[_field(f"field{i}", f"完整值{i}") for i in range(5000)],
            _field("Istr:1", "22", code="A002"),
        ],
        items=2,
    )
    text = _item(tmp_path, "装备", limit=1).render()
    assert "完整值4999" in text and "其余 1 条未显示" in text
    assert "  关联技能 [A002]" not in text


def test_ability_field_records_are_shared_between_items_in_the_index(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, [_link(), _link(item="I002"), _field("Istr:1", "11")], items=2)
    index = queries._load_item_ability_evidence(tmp_path)
    assert index.abilities_for("I001")[0] is index.abilities_for("I002")[0]


def test_multiple_ability_summaries_keep_their_source_identity(tmp_path: Path) -> None:
    _pack(
        tmp_path,
        [
            _link("A001, A002"),
            _field("Istr1", "11"),
            _field("Istr1", "22", code="A002"),
        ],
    )
    values = queries.load_item_equipped_effects(tmp_path)["I001"]
    assert len(values) == 2 and "A001" in values[0] and "A002" in values[1]


def test_conflicting_item_links_remain_explicit_in_the_summary(tmp_path: Path) -> None:
    _pack(
        tmp_path,
        [
            _link("A001"),
            _link("A002"),
            _field("Istr1", "11"),
            _field("Istr1", "22", code="A002"),
        ],
    )
    values = queries.load_item_equipped_effects(tmp_path)["I001"]
    assert len(values) == 2 and all("多种取值" in value for value in values)


def test_level_and_numeric_text_have_no_integer_conversion_ceiling(
    tmp_path: Path,
) -> None:
    level, value = "9" * 5000, "8" * 10000
    _pack(tmp_path, [_link(), _field("Istr:" + level, value)])
    summary = queries.load_item_equipped_effects(tmp_path)["I001"][0]
    assert value in summary and "等级 " + level in summary


def test_only_selected_items_are_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool.pack_query_item_abilities import ItemAbilityIndex

    _pack(
        tmp_path,
        [_link(item=f"I{i:03x}") for i in range(1, 11)] + [_field("Istr1", "11")],
        items=10,
    )
    rendered: list[str] = []
    real = ItemAbilityIndex.render_item

    def track(self: ItemAbilityIndex, item: str):
        rendered.append(item)
        return real(self, item)

    monkeypatch.setattr(ItemAbilityIndex, "render_item", track)
    assert _item(tmp_path, "装备", limit=1).exit_code == 0
    assert rendered == ["I001"]


def test_extra_field_columns_are_preserved_without_header_width_padding(
    tmp_path: Path,
) -> None:
    _pack(tmp_path, [_link()])
    path = tmp_path / "对象字段.tsv"
    _write(
        path,
        [
            [*_HEADER, "", "扩展字段8", *[f"声明{i}" for i in range(2000)]],
            _link(),
            [*_field("Iatt1", "123"), "无名附证", "有名附证"],
        ],
    )
    index = queries._load_item_ability_evidence(tmp_path)
    field = index.abilities_for("I001")[0].fields[0]
    assert len(field.extras) == 2
    text = _item(tmp_path).render()
    assert (
        "无名附证" in text
        and "有名附证" in text
        and "原列8" in text
        and "原列9" in text
    )


def test_same_size_mtime_updates_refresh_the_complete_ability_index(
    tmp_path: Path,
) -> None:
    import os

    path = _pack(tmp_path, [_link(), _field("Istr1", "11")])
    first = _item(tmp_path).render()
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"\t11\t", b"\t22\t"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = _item(tmp_path).render()
    assert "+11 力量" in first and "+22 力量" in second and "+11 力量" not in second
