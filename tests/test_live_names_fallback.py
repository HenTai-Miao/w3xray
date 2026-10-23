"""load_names BASE_NAMES_EN 兜底的 kind 匹配测试 (无知识包环境)。"""

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
    row = "x\tHpal\tx\tx\t圣骑士定制名\tx"
    (tsv_dir / "单位.tsv").write_text("c\tcode\tc2\tn\tname\tr\n" + row, encoding="utf-8")
    units = load_names(str(tmp_path), "单位")
    assert units.get(b"Hpal") == "圣骑士定制名"
