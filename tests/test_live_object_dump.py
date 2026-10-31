# -*- coding: utf-8 -*-
"""live --dump-objects 内存对象表导出的解析与落盘边界测试 (离线, 无需游戏)。"""

from __future__ import annotations

import csv
import ctypes
import ctypes.wintypes as wt
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gametool import live_object_dump as dump
from gametool.batch_tsv import decode_tsv_cell
from gametool.object_export_coverage import (
    OBJECT_COVERAGE_COLUMN,
    read_object_coverage_input,
)
from gametool.pack_query_objects import OBJECT_TABLES

from gametool.live_object_dump import (
    category_of,
    extract_affix_definitions,
    extract_registered_records,
    parse_slk_blocks,
    write_object_pack,
)


def _block(code: str, fields: dict[str, str]) -> bytes:
    body = b"\n\r\n[" + code.encode("latin-1") + b"\x00"
    for key, value in fields.items():
        body += b"\n" + key.encode() + b"\x00" + value.encode("utf-8") + b"\x00"
    return body


def _rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return [
            [decode_tsv_cell(cell) for cell in row]
            for row in csv.reader(stream, delimiter="\t", strict=True)
        ]


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

    def test_duplicate_blocks_preserve_all_sources_without_first_wins(self):
        first = _block("n00M", {"Name": "第一份"})
        second = _block("n00M", {"Name": "第二份"})
        data = first + second
        blocks, dup = parse_slk_blocks([(0x10000, data)])
        assert dup == 1
        assert "Name" not in blocks["n00M"]
        assert [record.raw for record in blocks.records] == [first, second]
        assert [record.address for record in blocks.records] == [
            0x10000,
            0x10000 + len(first),
        ]
        assert any("冲突" in note for note in blocks.diagnostics)

    def test_duplicate_across_regions(self):
        b = _block("h000", {"Name": "英雄"})
        blocks, dup = parse_slk_blocks([(0x10000, b), (0x20000, b)])
        assert dup == 1
        assert blocks["h000"]["Name"] == "英雄"
        assert [record.address for record in blocks.records] == [0x10000, 0x20000]
        assert all(record.raw == b for record in blocks.records)

    def test_multi_level_value_keeps_inner_separator(self):
        # 多级 NUL 是原始字段内容，不能替换为可能与源文相同的显示串。
        data = _block("n00M", {"Missilespeed": "1500\x001500"})
        blocks, _ = parse_slk_blocks([(0x10000, data)])
        assert blocks["n00M"]["Missilespeed"] == "1500\x001500"

    def test_region_without_blocks_ignored(self):
        blocks, dup = parse_slk_blocks([(0x10000, b"\x00" * 64)])
        assert blocks == {} and dup == 0

    def test_truncated_tail_remains_raw_evidence_with_diagnostic(self):
        data = _block("n00M", {"Name": "完整"}) + b"\nTip\x00" + "截断".encode("utf-8")
        blocks, _ = parse_slk_blocks([(0x10000, data)])
        assert "Tip" not in blocks["n00M"]
        assert blocks["n00M"]["Name"] == "完整"
        assert blocks.records[0].raw == data
        assert any("不完整" in note for note in blocks.diagnostics)

    def test_repeated_fields_invalid_utf8_and_significant_whitespace(self):
        data = (
            _block("=\xff! ", {"Name": "  原文\t\r ", "Data": "one"})
            + b"\nData\x00two\x00\nBroken\x00\xff\x00"
        )
        blocks, dup = parse_slk_blocks([(0x10000, data)])
        assert dup == 0 and len(blocks.records) == 1
        assert blocks["=\xff! "] == {"Name": "  原文\t\r "}
        fields = blocks.records[0].fields
        assert [field.key for field in fields] == ["Name", "Data", "Data", "Broken"]
        assert fields[-1].value is None and fields[-1].value_raw == b"\xff"
        assert fields[-1].diagnostics
        assert blocks.records[0].raw == data


class TestCategoryOf:
    @pytest.mark.parametrize(
        "code",
        (
            "I04W",
            "A001",
            "B000",
            "H000",
            "R000",
            "S000",
            "T001",
            "n00M",
            "hpea",
            "N020",
            "YTwf",
            "LTlt",
            "=\xff! ",
        ),
    )
    def test_prefix_does_not_certify_category(self, code):
        assert category_of(code) == "未分类"

    @pytest.mark.parametrize("code", ("", "abc", "abcde", "中文四码"))
    def test_invalid_identity_is_not_replaced_with_guessed_bytes(self, code):
        with pytest.raises(ValueError, match="四字节"):
            category_of(code)


class TestWriteObjectPack:
    def test_pack_has_partial_coverage_and_unclassified_text(self, tmp_path):
        blocks = {
            "I04W": {
                "Name": "副本-随机装备",
                "Ubertip": "最高可掉落紫色装备",
                "Sellitems": "",
            },
            "n00M": {"Name": "树人长者", "Tip": "召唤毒性树人"},
        }
        out = tmp_path / "pack"
        files = write_object_pack(blocks, str(out))
        assert files == len([path for path in out.rglob("*") if path.is_file()])
        for category in OBJECT_TABLES:
            rows = _rows(out / "对象ID" / f"{category}.tsv")
            assert len(rows) == 1 and OBJECT_COVERAGE_COLUMN in rows[0]
        assert len(_rows(out / "对象字段.tsv")) == 1
        rows = _rows(out / "未分类对象.tsv")
        assert [row[4] for row in rows[1:]] == ["副本-随机装备", "树人长者"]
        assert all(row[0] == "未分类" and row[3] == row[5] == "" for row in rows[1:])
        coverage = read_object_coverage_input(out).coverage
        assert coverage is not None
        assert dict(coverage.states) == dict.fromkeys(OBJECT_TABLES, "partial")
        assert any("运行时" in note for note in coverage.for_table())
        manifest = json.loads((out / "对象导出清单.json").read_bytes())
        assert manifest["completed"] is True
        assert manifest["map_coverage_complete"] is False
        for record in manifest["files"]:
            payload = (out / record["relative_path"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == record["sha256"]

    def test_name_falls_back_to_tip_then_code(self, tmp_path):
        blocks = {
            "n00X": {"Tip": "无名有提示"},
            "n00Y": {"Art": "a.blp"},
        }
        out = str(tmp_path / "pack")
        write_object_pack(blocks, out)
        with open(os.path.join(out, "未分类对象.tsv"), encoding="utf-8") as fh:
            units = fh.read()
        assert "无名有提示" in units
        assert "n00Y" in units

    @pytest.mark.parametrize(
        "value",
        (
            '带\t制表\n换行\r\n和"引号"',
            "=1+2",
            "'\u2060literal",
            "\ufeff@x",
            " a\x00b ",
        ),
    )
    def test_tsv_cells_round_trip_without_loss(self, tmp_path, value):
        blocks = {"=000": {"Name": value, "Ubertip": value}}
        out = tmp_path / "pack"
        write_object_pack(blocks, str(out))
        objects = _rows(out / "未分类对象.tsv")
        assert len(objects) == 2 and len(objects[0]) == len(objects[1])
        assert objects[1][1] == "=000"
        assert objects[1][4] == objects[1][6] == value
        fields = _rows(out / "未分类对象字段.tsv")
        assert [row[5] for row in fields[1:]] == [value, value]

    def test_raw_sources_and_duplicate_fields_survive_export(self, tmp_path):
        first = (
            _block("I001", {"Name": "first"}) + b"\nName\x00second\x00\nTail\x00broken"
        )
        second = _block("I001", {"Name": "third", "Data": " 1\x002 "})
        blocks, _ = parse_slk_blocks([(0x10000, first), (0x20000, second)])
        out = tmp_path / "pack"
        write_object_pack(blocks, str(out))
        raw = _rows(out / "内存对象原始块.tsv")
        assert [bytes.fromhex(row[5]) for row in raw[1:]] == [first, second]
        assert [row[2] for row in raw[1:]] == ["0x10000", "0x20000"]
        fields = _rows(out / "未分类对象字段.tsv")
        assert [row[5] for row in fields[1:]] == [
            "first",
            "second",
            "third",
            " 1\x002 ",
        ]
        assert "冲突" in (out / "对象来源.txt").read_text(encoding="utf-8")

    def test_existing_directory_is_unchanged(self, tmp_path):
        old = tmp_path / "对象字段.tsv"
        old.write_bytes(b"user evidence\r\n")
        before = old.read_bytes(), old.stat()
        with pytest.raises(ValueError, match="已有内容"):
            write_object_pack({"I001": {"Name": "replacement"}}, str(tmp_path))
        assert (old.read_bytes(), old.stat()) == before
        assert list(tmp_path.iterdir()) == [old]

    def test_real_junction_parent_is_rejected(self, tmp_path):
        target = tmp_path / "outside"
        target.mkdir()
        junction = tmp_path / "junction"
        importlib.import_module("_winapi").CreateJunction(str(target), str(junction))
        with pytest.raises(ValueError, match="ordinary|link"):
            write_object_pack({"I001": {"Name": "x"}}, str(junction / "pack"))
        assert not list(target.iterdir())

    def test_failed_publication_has_no_completion_manifest(self, tmp_path, monkeypatch):
        original = dump.write_report_bytes

        def fail(path, data):
            if Path(path).name == "未分类对象字段.tsv":
                raise OSError("injected disk failure")
            return original(path, data)

        monkeypatch.setattr(dump, "write_report_bytes", fail)
        out = tmp_path / "pack"
        with pytest.raises(OSError, match="injected disk failure"):
            write_object_pack({"I001": {"Name": "x"}}, str(out))
        assert not (out / "对象导出清单.json").exists()
        assert (out / "对象来源覆盖.tsv").exists()

    def test_changed_published_payload_is_not_confirmed_complete(
        self, tmp_path, monkeypatch
    ):
        original = dump.read_report_bytes

        def changed(path):
            data, metadata = original(path)
            return (
                (data + b"foreign", metadata)
                if Path(path).name == "未分类对象.tsv"
                else (data, metadata)
            )

        monkeypatch.setattr(dump, "read_report_bytes", changed)
        out = tmp_path / "pack"
        with pytest.raises(OSError, match="交付前变化"):
            write_object_pack({"I001": {"Name": "x"}}, str(out))
        assert not (out / "对象导出清单.json").exists()

    def test_coverage_is_revalidated_at_completion_publication(
        self, tmp_path, monkeypatch
    ):
        original = dump.write_report_bytes
        out = tmp_path / "pack"

        def changed(path, data, **kwargs):
            if Path(path).name == "对象导出清单.json":
                (out / "对象来源覆盖.tsv").write_bytes(b"changed sidecar")
            return original(path, data, **kwargs)

        monkeypatch.setattr(dump, "write_report_bytes", changed)
        with pytest.raises(ValueError, match="changed before final delivery"):
            write_object_pack({"I001": {"Name": "x"}}, str(out))
        assert not (out / "对象导出清单.json").exists()
        assert (out / "对象来源覆盖.tsv").read_bytes() == b"changed sidecar"


def _cloud_msg(name: str, params: list) -> bytes:  # pyright: ignore[reportMissingTypeArgument]
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

    @pytest.mark.parametrize(
        "info", ("[]", "null", "42", '"name"', "true", '{"name":"x","params":42}')
    )
    def test_non_object_or_non_array_info_is_retained_without_aborting(self, info):
        bad = json.dumps({"page": 1, "info": info}).encode()
        good = _cloud_msg("Good", [9])
        records = extract_registered_records([(0x10000, bad + b"\0" + good)])
        assert records["Good"]["records"] == [[9]]
        assert records.evidence[0].raw == bad
        assert records.evidence[0].diagnostics
        assert records.evidence[1].address == 0x10000 + len(bad) + 1

    def test_duplicate_roles_do_not_select_a_message_name(self):
        info = '{"name":"first","name":"second","params":[1]}'
        raw = json.dumps({"page": 1, "info": info}).encode()
        records = extract_registered_records([(10, raw)])
        assert not records
        assert records.evidence[0].raw == raw
        assert "重复" in records.evidence[0].diagnostics[0]

    def test_exact_json_numbers_duplicates_and_sources_are_exported(self, tmp_path):
        params = '[0.12345678901234567890123456789,-0,{"a":1,"a":2}]'
        info = '{"name":"=Msg","params":' + params + "}"
        raw = json.dumps({"page": 1, "info": info}).encode()
        records = extract_registered_records([(10, raw), (10000, raw)])
        assert not records  # 重复成员不能进入无歧义 dict 视图。
        assert len(records.evidence) == 2
        assert dump._write_registered_data_tsv(records, str(tmp_path)) == 2
        rows = _rows(tmp_path / "注册数据.tsv")
        assert [row[0] for row in rows[1:]] == ["=Msg", "=Msg"]
        assert [row[2] for row in rows[1:]] == [params, params]
        assert [row[3] for row in rows[1:]] == ["0xA", "0x2710"]
        evidence = _rows(tmp_path / "注册消息原始证据.tsv")
        assert [bytes.fromhex(row[3]) for row in evidence[1:]] == [raw, raw]

    def test_empty_params_is_a_complete_message_record(self):
        records = extract_registered_records([(10, _cloud_msg("Empty", []))])
        assert records["Empty"]["records"] == [[]]

    def test_invalid_unicode_name_stays_raw_without_breaking_later_messages(
        self, tmp_path
    ):
        info = '{"name":"\ud800","params":[1]}'
        raw = json.dumps({"page": 1, "info": info}).encode()
        records = extract_registered_records(
            [(10, raw + b"\0" + _cloud_msg("Good", [1]))]
        )
        assert records.evidence[0].raw == raw
        assert records.evidence[0].name == ""
        assert records.evidence[0].diagnostics
        dump._write_registered_data_tsv(records, str(tmp_path))
        assert _rows(tmp_path / "注册数据.tsv")[1][0] == "Good"

    def test_large_json_depth_and_integer_have_no_interpreter_quota(self, tmp_path):
        params = "[" * 1200 + "9" * 5000 + "]" * 1200
        raw = json.dumps(
            {"page": 1, "info": '{"name":"Deep","params":' + params + "}"}
        ).encode()
        records = extract_registered_records([(10, raw)])
        assert len(records.evidence) == 1 and not records.evidence[0].diagnostics
        dump._write_registered_data_tsv(records, str(tmp_path))
        assert _rows(tmp_path / "注册数据.tsv")[1][2] == params


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

    def test_conflicting_same_name_affixes_keep_each_definition_and_address(
        self, tmp_path
    ):
        first = "甲：提供|cff00ff00（LV*1）|r点攻击".encode()
        second = "甲：提供|cff00ff00（LV*2）|r点防御".encode()
        definitions = extract_affix_definitions([(10, first), (1000, second)])
        assert "甲" not in definitions
        assert [record.raw for record in definitions.evidence] == [first, second]
        assert dump._write_affixes_tsv(definitions, str(tmp_path)) == 1
        rows = _rows(tmp_path / "词缀表.tsv")
        assert [row[:3] for row in rows[1:]] == [
            ["甲", "1", "攻击"],
            ["甲", "2", "防御"],
        ]
        assert all("不同原文" in row[-1] for row in rows[1:])


class TestDumpWritesLuaLayer:
    def test_pack_includes_registered_and_affix_tsv(self, tmp_path):
        blocks = {"I001": {"Name": "X", "Ubertip": "Y"}}
        out = str(tmp_path / "pack")
        files = write_object_pack(blocks, out)
        assert files == 16
        # 单独验证两个 Lua 层写盘函数
        from gametool.live_object_dump import (
            _write_affixes_tsv,
            _write_registered_data_tsv,
        )

        reg = {"MsgA": {"records": [[1, {"k": "v"}], [2, {"k": "w"}]]}}
        assert _write_registered_data_tsv(reg, out) == 1  # pyright: ignore[reportArgumentType]
        with open(os.path.join(out, "注册数据.tsv"), encoding="utf-8") as fh:
            rows = fh.read().splitlines()
        assert rows[0].split("\t") == ["消息名", "序号", "记录JSON"]
        assert len(rows) == 3
        aff = {"甲": {"multiplier": "1.5", "stat": "点物理攻击"}}
        assert _write_affixes_tsv(aff, out) == 1
        with open(os.path.join(out, "词缀表.tsv"), encoding="utf-8") as fh:
            arows = fh.read().splitlines()
        assert arows[0].split("\t") == ["词缀名", "倍率", "属性"]
        # 空数据不写文件
        assert _write_registered_data_tsv({}, out) == 0
        assert _write_affixes_tsv({}, out) == 0

    def test_auxiliary_writers_do_not_overwrite_existing_evidence(self, tmp_path):
        registered = tmp_path / "注册数据.tsv"
        registered.write_bytes(b"registered old")
        affixes = tmp_path / "词缀表.tsv"
        affixes.write_bytes(b"affixes old")
        with pytest.raises(ValueError, match="already exists"):
            dump._write_registered_data_tsv({"M": {"records": [[1]]}}, str(tmp_path))
        with pytest.raises(ValueError, match="already exists"):
            dump._write_affixes_tsv(
                {"A": {"multiplier": "1", "stat": "B"}}, str(tmp_path)
            )
        assert registered.read_bytes() == b"registered old"
        assert affixes.read_bytes() == b"affixes old"


class TestRegionGuardDisclosure:
    """超大区域护栏不得静默: 跳过必须计数, 披露字段禁止省略。

    (369 轮: 旧版单区域超 256MB 直接跳过, 扫描区域行无任何跳过痕迹)
    """

    def test_skip_over_cap_reads_within_cap(self):
        from gametool.live_object_dump import _region_action

        # 常规可读区域: read
        assert _region_action(0x1000, 0x04, 0x100000) == "read"
        # 同保护属性但超过护栏: skip (计数, 不静默丢)
        assert _region_action(0x1000, 0x04, 0x10000000 + 0x1000) == "read"
        # 非提交/非可读保护: ignore (与上限无关)
        assert _region_action(0x2000, 0x04, 0x1000) == "ignore"
        assert _region_action(0x1000, 0x01, 0x1000) == "ignore"

    def test_note_discloses_zero_and_positive_counts(self):
        from gametool.live_object_dump import _skipped_regions_note

        assert _skipped_regions_note(0) == "无"
        assert "3 个内存片段未完整读取" in _skipped_regions_note(3)
        assert "页面不可读" in _skipped_regions_note(3)

    @pytest.mark.parametrize("protect", (0x08, 0x204, 0x404))
    def test_copy_and_cache_protections_remain_readable(self, protect):
        assert dump._region_action(0x1000, protect, 0x1000) == "read"
        assert dump._region_action(0x1000, protect | 0x100, 0x1000) == "ignore"


def test_native_snapshot_has_pointer_width_signatures_and_retains_short_reads(
    monkeypatch,
):
    handle = 0x1234567812345678
    addresses = []

    def query(actual_handle, address, result, size):
        assert actual_handle == handle
        if address.value == 0x10008:
            return 0
        result._obj.Base = 0x10000
        result._obj.RegionSize = 8
        result._obj.State = 0x1000
        result._obj.Protect = 0x04
        return size

    def read(actual_handle, address, buffer, requested, got):
        assert actual_handle == handle
        addresses.append(address.value)
        data = b"abc" if address.value == 0x10000 else b"efgh"
        assert requested == 4
        ctypes.memmove(buffer, data, len(data))
        got._obj.value = len(data)
        return len(data) == requested

    api = SimpleNamespace(VirtualQueryEx=query, ReadProcessMemory=read)
    monkeypatch.setattr(dump.ctypes, "WinDLL", lambda *_a, **_kw: api)
    monkeypatch.setattr(dump, "_READ_CHUNK_BYTES", 4)
    regions, total, skipped = dump._snapshot_regions(handle, 0x20000)
    assert regions == [(0x10000, b"abc"), (0x10004, b"efgh")]
    assert total == 7 and skipped == 2
    assert addresses == [0x10000, 0x10004]
    assert api.VirtualQueryEx.argtypes[0] is wt.HANDLE
    assert api.VirtualQueryEx.restype is ctypes.c_size_t
    assert api.ReadProcessMemory.argtypes[0] is wt.HANDLE
    assert api.ReadProcessMemory.argtypes[3] is ctypes.c_size_t
    assert isinstance(regions, dump.CapturedRegions)
    assert any("VirtualQueryEx" in note for note in regions.diagnostics)
    assert any("ReadProcessMemory" in note for note in regions.diagnostics)


def test_native_snapshot_rejects_nonprogressing_regions(monkeypatch):
    def query(_handle, _address, result, size):
        result._obj.Base = 0x10000
        result._obj.RegionSize = 0
        return size

    def forbidden(*_args):
        raise AssertionError("nonprogressing regions are not readable evidence")

    monkeypatch.setattr(
        dump.ctypes,
        "WinDLL",
        lambda *_a, **_kw: SimpleNamespace(
            VirtualQueryEx=query, ReadProcessMemory=forbidden
        ),
    )
    regions, total, skipped = dump._snapshot_regions(1, 0x20000)
    assert not regions and total == 0 and skipped == 1
    assert isinstance(regions, dump.CapturedRegions)
    assert "不前进" in regions.diagnostics[0]


def test_close_handle_configures_its_own_pointer_width_api(monkeypatch):
    seen = []

    def close(handle):
        seen.append(handle)
        return True

    api = SimpleNamespace(CloseHandle=close)
    monkeypatch.setattr(dump.ctypes, "WinDLL", lambda *_a, **_kw: api)
    dump._close_process_handle(0x1234567812345678)
    assert seen == [0x1234567812345678]
    assert api.CloseHandle.argtypes == [wt.HANDLE]
    assert api.CloseHandle.restype is wt.BOOL


@pytest.mark.parametrize("kind", ("object", "registered", "affix", "empty"))
def test_dump_result_counts_delivered_evidence_and_keeps_read_diagnostics(
    tmp_path, monkeypatch, kind
):
    from gametool import live_inventory as live

    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    version = {"arch": "x64", "version": "synthetic", "diagnostics": ["module gap"]}
    monkeypatch.setattr(live, "detect_version", lambda _h: version)
    monkeypatch.setattr(live, "process_scan_limit", lambda _v: 0x20000)
    regions = dump.CapturedRegions()
    payloads = {
        "object": _block("I001", {"Name": "x"}),
        "registered": _cloud_msg("Msg", []),
        "affix": "甲：提供|cff00ff00（LV*1）|r点攻击".encode(),
        "empty": b"unrecognized",
    }
    regions.append((0x10000, payloads[kind]))
    regions.diagnostics.append("synthetic missing page")
    monkeypatch.setattr(
        dump, "_snapshot_regions", lambda _h, _limit: (regions, len(payloads[kind]), 1)
    )
    closed = []
    monkeypatch.setattr(dump, "_close_process_handle", closed.append)
    out = tmp_path / "pack"
    result = dump.dump_live_objects(str(out), verbose=False)
    assert result.completed and result.files > 0
    assert closed == [123]
    assert result.records == result.objects == int(kind == "object")
    assert result.registered_records == int(kind == "registered")
    assert result.affix_records == int(kind == "affix")
    assert "module gap" in result.notes and "synthetic missing page" in result.notes
    coverage = read_object_coverage_input(out).coverage
    assert coverage is not None
    assert "synthetic missing page" in "\n".join(coverage.for_table())
