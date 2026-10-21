# -*- coding: utf-8 -*-
"""live --dump-objects 内存对象表导出的解析与落盘边界测试 (离线, 无需游戏)。"""

from __future__ import annotations

import os

from gametool.live_object_dump import (
    category_of,
    extract_affix_definitions,
    extract_registered_records,
    parse_slk_blocks,
    write_object_pack,
)


def _block(code: str, fields: dict[str, str]) -> bytes:
    body = b"\n\r\n[" + code.encode() + b"\x00"
    for key, value in fields.items():
        body += b"\n" + key.encode() + b"\x00" + value.encode("utf-8") + b"\x00"
    return body


class TestParseSlkBlocks:
    def test_basic_split_and_fields(self):
        data = _block("n00M", {"Name": "树人长者", "Tip": "召唤毒性树人"}) + _block(
            "I04W", {"Name": "副本-随机装备", "Ubertip": "最高可掉落紫色装备"}
        )
        blocks, dup = parse_slk_blocks([(0x10000, data)])
        assert dup == 0
        assert blocks["n00M"]["Name"] == "树人长者"
        assert blocks["I04W"]["Ubertip"] == "最高可掉落紫色装备"

    def test_first_block_in_region(self):
        # 表首块以 \r\n[ 开头 (无前置 \n)
        data = b"\r\n[n00M\x00\nName\x00" + "树人长者".encode("utf-8") + b"\x00"
        blocks, _ = parse_slk_blocks([(0x10000, data)])
        assert blocks["n00M"]["Name"] == "树人长者"

    def test_duplicate_blocks_counted_first_wins(self):
        data = _block("n00M", {"Name": "第一份"}) + _block("n00M", {"Name": "第二份"})
        blocks, dup = parse_slk_blocks([(0x10000, data)])
        assert dup == 1
        assert blocks["n00M"]["Name"] == "第一份"

    def test_duplicate_across_regions(self):
        b = _block("h000", {"Name": "英雄"})
        blocks, dup = parse_slk_blocks([(0x10000, b), (0x20000, b)])
        assert dup == 1
        assert blocks["h000"]["Name"] == "英雄"

    def test_multi_level_value_keeps_inner_separator(self):
        # Missilespeed 的多级值内层 \x00 转 " | "
        data = _block("n00M", {"Missilespeed": "1500\x001500"})
        blocks, _ = parse_slk_blocks([(0x10000, data)])
        assert blocks["n00M"]["Missilespeed"] == "1500 | 1500"

    def test_region_without_blocks_ignored(self):
        blocks, dup = parse_slk_blocks([(0x10000, b"\x00" * 64)])
        assert blocks == {} and dup == 0

    def test_truncated_block_tail_ignored(self):
        # 末尾缺结束 \x00 的字段被丢弃 (不产出半截值)
        data = _block("n00M", {"Name": "完整"}) + b"\nTip\x00" + "截断".encode("utf-8")
        blocks, _ = parse_slk_blocks([(0x10000, data)])
        assert "Tip" not in blocks["n00M"]
        assert blocks["n00M"]["Name"] == "完整"


class TestCategoryOf:
    def test_known_prefixes(self):
        assert category_of("I04W") == "物品"
        assert category_of("A001") == "技能"
        assert category_of("B000") == "增益"
        assert category_of("H000") == "英雄"
        assert category_of("R000") == "科技"
        assert category_of("S000") == "科技"
        assert category_of("T001") == "道具技能"

    def test_lowercase_and_custom_are_units(self):
        assert category_of("n00M") == "单位"
        assert category_of("hpea") == "单位"
        assert category_of("N020") == "单位"
        assert category_of("YTwf") == "单位"
        assert category_of("LTlt") == "单位"


class TestWriteObjectPack:
    def test_pack_writes_compatible_tsv(self, tmp_path):
        blocks = {
            "I04W": {
                "Name": "副本-随机装备",
                "Ubertip": "最高可掉落紫色装备",
                "Sellitems": "",
            },
            "n00M": {"Name": "树人长者", "Tip": "召唤毒性树人"},
        }
        out = str(tmp_path / "pack")
        files = write_object_pack(blocks, out)
        assert files == 4  # 对象ID/物品 + 对象ID/单位 + 对象字段 + 对象来源
        items = open(os.path.join(out, "对象ID", "物品.tsv"), encoding="utf-8").read()
        assert "I04W\t" in items and "副本-随机装备" in items
        units = open(os.path.join(out, "对象ID", "单位.tsv"), encoding="utf-8").read()
        assert "树人长者" in units
        fields = open(os.path.join(out, "对象字段.tsv"), encoding="utf-8").read()
        # 字段行来源列 = 内存对象表 (pack_query load_shop_stocks 兼容 7 列)
        assert "内存对象表" in fields
        assert fields.splitlines()[0].split("\t") == [
            "分类",
            "ID",
            "名称",
            "字段键",
            "字段名",
            "值",
            "来源",
        ]
        assert open(os.path.join(out, "对象来源.txt"), encoding="utf-8").read()

    def test_name_falls_back_to_tip_then_code(self, tmp_path):
        blocks = {
            "n00X": {"Tip": "无名有提示"},
            "n00Y": {"Art": "a.blp"},
        }
        out = str(tmp_path / "pack")
        write_object_pack(blocks, out)
        units = open(os.path.join(out, "对象ID", "单位.tsv"), encoding="utf-8").read()
        assert "无名有提示" in units
        assert "n00Y" in units

    def test_tsv_injection_escaped(self, tmp_path):
        blocks = {"I000": {"Name": "带\t制表\n换行", "Ubertip": "x"}}
        out = str(tmp_path / "pack")
        write_object_pack(blocks, out)
        items = open(os.path.join(out, "对象ID", "物品.tsv"), encoding="utf-8").read()
        # 列数不因值内换行/制表而爆掉
        row = [r for r in items.splitlines() if r.startswith("物品\tI000")][0]
        assert len(row.split("\t")) == 7


def _cloud_msg(name: str, params: list) -> bytes:
    """构造真实内存形态的云消息字节 (info 为嵌套 JSON 字符串)。"""
    import json

    info = json.dumps({"name": name, "params": params}, ensure_ascii=False)
    outer = json.dumps({"page": 1, "info": info}, ensure_ascii=False)
    return outer.encode("utf-8")


class TestExtractRegisteredRecords:
    """云消息注册数据提取 — 合成样本验证无地图特定词表。"""

    def test_json_cloud_message_generic(self):
        # 任意消息名都能收 (非千风物语词表): 用完全编造的 MapX/Y 名
        msg = _cloud_msg("RegisterThing", [7, {"k": "abc-1", "v": 99}])
        got = extract_registered_records([(0x10000, msg + b"\x00")])
        assert "RegisterThing" in got
        assert got["RegisterThing"]["records"] == [[7, {"k": "abc-1", "v": 99}]]

    def test_dedup_same_payload(self):
        msg = _cloud_msg("E", [1, {"a": 2}])
        got = extract_registered_records([(0x10000, (msg + b"\x00") * 3)])
        assert len(got["E"]["records"]) == 1

    def test_same_name_different_params_kept(self):
        a = _cloud_msg("E", [1, {"x": 1}])
        b = _cloud_msg("E", [1, {"x": 2}])
        got = extract_registered_records([(0x10000, a + b"\x00" + b)])
        assert len(got["E"]["records"]) == 2

    def test_garbage_skipped_fail_open(self):
        noise = b'{"page":1,"info":"not-json\x00{"page":2,"info":"{\\"name\\":\\"OK\\",\\"params\\":[1]}"}\x00'
        got = extract_registered_records([(0x10000, noise)])
        assert list(got) == ["OK"]

    def test_no_messages_empty(self):
        assert extract_registered_records([(0x10000, b"\x00" * 128)]) == {}


class TestExtractAffixDefinitions:
    """词缀公式提取 — 模式驱动, 任意词条名都能收。"""

    def test_basic_affix(self):
        # 完全编造的词缀 (非千风物语): 测试通用性
        blob = "幻影：提供|cff00ff00（LV*9.9）|r点月亮力量".encode("utf-8")
        got = extract_affix_definitions([(0x10000, blob)])
        assert got["幻影"] == {"multiplier": "9.9", "stat": "月亮力量"}

    def test_de_form_variant(self):
        blob = "铁壁：提供|cff00ff00（LV*0.1）|r的免伤率".encode("utf-8")
        got = extract_affix_definitions([(0x10000, blob)])
        assert got["铁壁"] == {"multiplier": "0.1", "stat": "免伤率"}

    def test_dedup_and_multi(self):
        blob = (
            "甲：提供|cff00ff00（LV*1）|r点攻击".encode("utf-8")
            + b"\x00\x00"
            + "甲：提供|cff00ff00（LV*1）|r点攻击".encode("utf-8")
            + b"\x00\x00"
            + "乙：提供|cff00ff00（LV*2）|r点防御".encode("utf-8")
        )
        got = extract_affix_definitions([(0x10000, blob)])
        assert len(got) == 2
        assert got["乙"]["multiplier"] == "2"

    def test_no_affixes_empty(self):
        assert extract_affix_definitions([(0x10000, b"\x00" * 64)]) == {}


class TestDumpWritesLuaLayer:
    def test_pack_includes_registered_and_affix_tsv(self, tmp_path):
        blocks = {"I001": {"Name": "X", "Ubertip": "Y"}}
        out = str(tmp_path / "pack")
        files = write_object_pack(blocks, out)
        assert files == 3  # 对象ID/物品 + 对象字段 + 对象来源
        # 单独验证两个 Lua 层写盘函数
        from gametool.live_object_dump import (
            _write_affixes_tsv,
            _write_registered_data_tsv,
        )

        reg = {"MsgA": {"records": [[1, {"k": "v"}], [2, {"k": "w"}]]}}
        assert _write_registered_data_tsv(reg, out) == 1
        rows = (
            open(os.path.join(out, "注册数据.tsv"), encoding="utf-8")
            .read()
            .splitlines()
        )
        assert rows[0].split("\t") == ["消息名", "序号", "记录JSON"]
        assert len(rows) == 3
        aff = {"甲": {"multiplier": "1.5", "stat": "点物理攻击"}}
        assert _write_affixes_tsv(aff, out) == 1
        arows = (
            open(os.path.join(out, "词缀表.tsv"), encoding="utf-8").read().splitlines()
        )
        assert arows[0].split("\t") == ["词缀名", "倍率", "属性"]
        # 空数据不写文件
        assert _write_registered_data_tsv({}, out) == 0
        assert _write_affixes_tsv({}, out) == 0
