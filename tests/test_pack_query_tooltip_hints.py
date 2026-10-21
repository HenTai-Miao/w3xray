# -*- coding: utf-8 -*-
"""pack-query 文案层兜底：关系表与脚本奖池无记录时，从对象说明文本提取配方/来源线索。

历史动因（KKWE 加密图实测）：合成与掉落触发在加密脚本里读不到，但作者把配方和
掉落点写在了材料/传送物品的说明文本里（如"不熄的火焰 x 4 = 不死鸟天翔"、"地狱火
掉落：不熄的火焰"）。where/drop 不得止步于"未找到"，必须回落文案层并标注未脚本验证。
"""

from __future__ import annotations

from gametool.pack_query_cli import (
    _script_encrypted,
    _tooltip_source_hints,
    parse_pack_query_cli_options,
    run_pack_query_cli,
)

_ITEMS_TSV = (
    "物品\t四码\t数值\t四码2\t名称\t英雄\t描述\n"
    "物品\tI03B\t1\tI03B\t不熄的火焰\t是\t材料。 不熄的火焰 x 4 = 不死鸟天翔 不熄的火焰 + 火焰宝石 + 黑龙之魂 = 寂灭之力\n"
    "物品\tI03G\t2\tI03G\t火焰宝石\t是\t材料。 火焰宝石 + 不熄的火焰 + 黑龙之魂 = 寂灭之力\n"
    "物品\tI03H\t3\tI03H\t黑龙之魂\t是\t材料。 火焰宝石 + 不熄的火焰 + 黑龙之魂 = 寂灭之力\n"
    "物品\tI03K\t4\tI03K\t传送：焰冰之地\t是\t地狱火掉落：不熄的火焰\n"
    "物品\tI03X\t5\tI03X\t不死鸟天翔\t是\t材料。\n"
    "物品\tI03Y\t6\tI03Y\t寂灭之力\t是\t材料。\n"
)


def _make_pack(tmp_path, encrypted: bool = True) -> None:
    obj = tmp_path / "对象ID"
    obj.mkdir()
    (obj / "物品.tsv").write_text(_ITEMS_TSV, encoding="utf-8")
    if encrypted:
        enc = tmp_path / "未知文件"
        enc.mkdir()
        (enc / "加密脚本检测.txt").write_text("KKWE", encoding="utf-8")


def test_hints_collected_and_encrypted_flag(tmp_path):
    _make_pack(tmp_path)
    assert _script_encrypted(tmp_path) is True
    hints = _tooltip_source_hints(tmp_path, {"寂灭之力"}, 8)
    assert any("不熄的火焰" in h and "I03B" in h for h in hints)
    hints_x = _tooltip_source_hints(tmp_path, {"不死鸟天翔"}, 8)
    assert any("不熄的火焰 x 4" in h for h in hints_x)
    hints_b = _tooltip_source_hints(tmp_path, {"不熄的火焰"}, 8)
    assert any("地狱火掉落" in h and "传送：焰冰之地" in h for h in hints_b)


def test_drop_falls_back_to_tooltip_hints(tmp_path, capsys):
    _make_pack(tmp_path)
    opts = parse_pack_query_cli_options([str(tmp_path), "drop", "I03Y"])
    rc = run_pack_query_cli(opts)
    out = capsys.readouterr().out
    assert rc == 0
    assert "文案级配方/来源线索" in out
    assert "脚本加密" in out
    assert "不熄的火焰" in out


def test_drop_name_query_falls_back(tmp_path, capsys):
    _make_pack(tmp_path)
    opts = parse_pack_query_cli_options([str(tmp_path), "drop", "不死鸟天翔"])
    rc = run_pack_query_cli(opts)
    out = capsys.readouterr().out
    assert rc == 0
    assert "不熄的火焰 x 4" in out


def test_drop_no_hints_still_reports_missing(tmp_path, capsys):
    _make_pack(tmp_path, encrypted=False)
    opts = parse_pack_query_cli_options([str(tmp_path), "drop", "不存在的物品"])
    rc = run_pack_query_cli(opts)
    out = capsys.readouterr().out
    assert rc == 2
    assert "未找到获取途径" in out


def test_where_falls_back_with_plain_header(tmp_path, capsys):
    _make_pack(tmp_path, encrypted=False)
    opts = parse_pack_query_cli_options([str(tmp_path), "where", "寂灭之力"])
    rc = run_pack_query_cli(opts)
    out = capsys.readouterr().out
    assert rc == 0
    assert "文案级来源线索" in out
    assert "脚本加密" not in out
    assert "不熄的火焰" in out
