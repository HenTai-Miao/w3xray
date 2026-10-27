"""load_names BASE_NAMES_EN 兜底的 kind 匹配测试 (无知识包环境)。"""

import pytest

from gametool.live_inventory import load_names


def test_load_names_units_fallback_without_pack(tmp_path):
    """无包时单位名兜底来自 BASE_NAMES_EN (旧版恒 item 过滤 → 单位全 '?')。"""
    units = load_names(str(tmp_path), "单位")
    assert len(units) > 500
    assert units.get(b"Hpal") == "Paladin"


def test_load_names_items_fallback_without_pack(tmp_path):
    items = load_names(str(tmp_path), "物品")
    assert len(items) > 300


def test_load_names_pack_tsv_overrides_fallback(tmp_path):
    """包内 TSV 优先于 BASE_NAMES_EN 兜底 (setdefault 语义)。"""
    tsv_dir = tmp_path / "对象ID"
    tsv_dir.mkdir()
    row = "单位\tHpal\t0\tHpal\t圣骑士定制名\t是\t"
    (tsv_dir / "单位.tsv").write_text(
        "分类\tID\t10进制\t基础ID\t名称\t自定义\t说明\n" + row,
        encoding="utf-8",
    )
    units = load_names(str(tmp_path), "单位")
    assert units.get(b"Hpal") == "圣骑士定制名"


@pytest.mark.parametrize(
    "header, row",
    (
        (
            "分类\t未声明身份\t数值\t基础ID\t名称",
            "单位\tHpal\t0\tHpal\t伪造地图名称",
        ),
        (
            "分类\tID\t四码\t基础ID\t名称",
            "单位\tHpal\thfoo\tHpal\t伪造地图名称",
        ),
    ),
)
def test_load_names_does_not_guess_invalid_or_ambiguous_columns(tmp_path, header, row):
    tsv_dir = tmp_path / "对象ID"
    tsv_dir.mkdir()
    (tsv_dir / "单位.tsv").write_text(header + "\n" + row, encoding="utf-8")

    assert load_names(str(tmp_path), "单位").get(b"Hpal") == "Paladin"
