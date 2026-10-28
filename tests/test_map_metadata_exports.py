"""Real parser-to-page/export contracts for scoped W3I and WTS evidence."""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import struct

import pytest

from gametool.extraction_diagnostics import record_component_failure
from gametool.extraction_profile import ALL_CATEGORIES, ExtractionProfile
from gametool.gameconfig import GameConfiguration, NamedGameConfiguration
from gametool.knowledge_pack import (
    write_knowledge_pack_family_report,
    write_knowledge_pack_report,
)
from gametool.knowledge_results import KnowledgeWriteStatus
from gametool.load_context import MapLoadContext
from gametool.map_components import _add_w3i
from gametool.map_data import MapData
from gametool.map_info import format_map_info
from gametool.map_loader import _load_map_impl
from gametool.map_metadata_exports import (
    format_map_metadata_evidence,
    format_map_string_evidence,
)
from gametool.wts import parse_wts_evidence, retain_wts_evidence
from tests.test_object_pipeline import FakeArchive
from tests.test_w3i_metadata import _document


def _load(files: dict[str, bytes], path: str = "fixture.w3x") -> MapData:
    archive = FakeArchive(files)
    archive.path = path
    md = _load_map_impl(archive, path, 0, None, MapLoadContext())
    # This in-memory archive has no physical MPQ to reopen for anonymous-block
    # export. Its parsed metadata remains sufficient for the real pack writer.
    md.archive_source = None
    return md


def _basic_profile(enabled: bool = True) -> ExtractionProfile:
    return ExtractionProfile(
        {name: enabled and name == "basic" for name in ALL_CATEGORIES}
    )


def _strings(text: str) -> bytes:
    return ("STRING 1\r\n{\r\n" + text + "\r\n}\r\n").encode("utf-8")


def _reconstructed_w3i(document: dict[str, object]) -> bytes:
    info = document["w3i"]
    assert isinstance(info, dict)
    return b"".join(
        bytes.fromhex(row["raw"]["data"]) for row in info["fields"]
    ) + bytes.fromhex(info["unconsumed_data"]["data"])


def test_map_info_lists_every_metadata_family_player_and_table_instance() -> None:
    d = _document(39, player_count=129, upgrade_count=255, columns=257)
    md = _load({"war3map.w3i": bytes(d.data), "war3map.wts": _strings("完整地图")})
    text = format_map_info(md)
    for expected in (
        "完整地图",
        "地图保存版本：37",
        "编辑器版本：6060",
        "游戏版本（4 个分量）：(1, 32, 10, 18820)",
        "载入画面标题：加载标题",
        "序章副标题：序章副标题",
        "雾最大不透明度：0.75",
        "HD 水面波浪法线强度原值：77",
        "HD 水面环境贴图反射率原值：88",
        "透明地块小地图颜色（BGRA）：(13, 14, 15, 16)",
        "默认镜头缩放原值：1650",
        "最小镜头缩放原值：900",
        "游戏数据集：2",
        "游戏数据版本：1（TFT）",
        "P129 玩家128",
        "敌人低/高优先级",
        "0x80000000",
        "共享高级控制=是",
        "#255 ID='Rÿ !'",
        "ID=' A  '",
        "列256='I001'",
        "ID='I002'",
        "集合 #2 · 已保留 0 项 · 完整",
        "W3I 解析：完整",
    ):
        assert expected in text, expected
    assert "另 " not in text


def test_each_typed_w3i_issue_reaches_component_diagnostics_and_page() -> None:
    d = _document(31)
    data = bytearray(d.replace("script", struct.pack("<i", 77)))
    struct.pack_into("<I", data, d.offsets["flags"], 0x80000004)
    archive = FakeArchive({"war3map.w3i": bytes(data)})
    md = MapData(archive.path, "原地图名")
    _add_w3i(md, archive, {})
    assert md.w3i is not None and len(md.w3i.diagnostics) == 2
    assert len(md.diagnostics) == 2
    for source_issue, retained in zip(md.w3i.diagnostics, md.diagnostics, strict=True):
        assert retained.stage == f"parse/{source_issue.code.value}"
        assert retained.exception_type == "ComponentParseError"
        assert source_issue.field in retained.message
        assert f"byte {source_issue.offset}" in retained.message
        assert source_issue.message in format_map_info(md)
    exported = json.loads(format_map_metadata_evidence(md))
    assert len(exported["diagnostics"]) == len(exported["w3i"]["diagnostics"]) == 2
    assert exported["w3i"]["script_type"] == "unknown"
    assert not exported["complete"]
    assert _reconstructed_w3i(exported) == data


@pytest.mark.parametrize("kind", ("unknown", "truncated"))
def test_unknown_or_truncated_w3i_keeps_raw_tail_and_never_claims_empty_tables(
    kind: str,
) -> None:
    d = _document(31)
    raw = (
        d.replace("version", struct.pack("<i", 34))
        if kind == "unknown"
        else bytes(d.data[: d.offsets["script"] + 2])
    )
    md = _load({"war3map.w3i": raw})
    exported = json.loads(format_map_metadata_evidence(md))
    assert exported["w3i"]["script_type"] == "unknown"
    assert not exported["complete"] and not exported["w3i"]["tables_complete"]
    assert exported["w3i"]["unconsumed_data"]["data"]
    assert _reconstructed_w3i(exported) == raw
    text = format_map_info(md)
    assert "声明数量未确认" in text and "部分或存在未知值" in text
    assert "声明 0 条" not in text


def test_omitted_optional_tables_stay_distinct_from_explicit_empty_tables() -> None:
    d = _document(31)
    omitted = bytes(d.data[: d.offsets["upgrades"]]) + b"\xff"
    md = _load({"war3map.w3i": omitted})
    exported = json.loads(format_map_metadata_evidence(md))
    assert exported["complete"] and exported["w3i"]["optional_data_skipped"]
    assert not exported["w3i"]["tables_complete"]
    text = format_map_info(md)
    assert "不能据此认定这些表为空" in text and "源表已省略" in text
    assert "升级可用性（声明 0 条" not in text
    explicit = bytes(d.data[: d.offsets["upgrades"]]) + struct.pack("<4i", 0, 0, 0, 0)
    md = _load({"war3map.w3i": explicit})
    assert "升级可用性（声明 0 条；已保留 0 条；完整读取）" in format_map_info(md)


def test_nonfinite_and_lossy_fields_use_strict_json_and_preserve_exact_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import w3i_reader

    monkeypatch.setattr(w3i_reader, "default_legacy_codecs", lambda: ("gbk", "gb18030"))
    d = _document(39)
    data = bytearray(d.replace("camera_bounds", struct.pack("<f", math.nan)))
    struct.pack_into("<f", data, d.offsets["player0.position"], math.inf)
    data = data[: d.offsets["map_name"]] + b"\x81\0" + data[d.offsets["author"] :]
    md = _load({"war3map.w3i": bytes(data)})
    exported = json.loads(
        format_map_metadata_evidence(md),
        parse_constant=lambda value: pytest.fail(value),
    )
    assert not exported["complete"]
    assert {item["code"] for item in exported["w3i"]["diagnostics"]} == {
        "invalid_value",
        "lossy_string",
    }
    assert _reconstructed_w3i(exported) == data
    text = format_map_info(md)
    assert "镜头边界（8 个分量）：未确认有效值" in text
    assert "起点：X=未确认" in text and "[lossy_string] map_name" in text


def test_wts_conflicts_and_map_campaign_domains_keep_every_raw_record() -> None:
    map_raw = (
        _strings("first map value")
        + _strings("second map value")
        + b"STRING 2\n{\nvalid\n}\n"
    )
    campaign_raw = _strings("campaign value")
    md = _load(
        {
            "war3map.w3i": bytes(_document(31).data),
            "war3map.wts": map_raw,
            "war3campaign.wts": campaign_raw,
        }
    )
    exported = json.loads(format_map_string_evidence(md))
    sources = {source["member"]: source for source in exported["sources"]}
    assert exported["parsed_source_count"] == 2 and not exported["complete"]
    assert base64.b64decode(sources["war3map.wts"]["raw_bytes_base64"]) == map_raw
    assert (
        base64.b64decode(sources["war3campaign.wts"]["raw_bytes_base64"])
        == campaign_raw
    )
    assert [row["state"] for row in sources["war3map.wts"]["records"]] == [
        "conflict",
        "conflict",
        "confirmed",
    ]
    assert sources["war3map.wts"]["confirmed"] == [{"string_id": "2", "text": "valid"}]
    assert sources["war3campaign.wts"]["confirmed"] == [
        {"string_id": "1", "text": "campaign value"}
    ]
    assert md.w3i is not None and md.w3i.map_name == "TRIGSTR_001"
    assert exported["diagnostics"] and sources["war3map.wts"]["diagnostics"]


def test_equal_wts_duplicates_keep_typed_completeness_and_all_source_evidence() -> None:
    md = MapData("duplicate.w3x", "重复同值")
    raw = _strings("same") * 5
    retain_wts_evidence(md, parse_wts_evidence(raw, source="war3map.wts"))
    exported = json.loads(format_map_string_evidence(md))
    assert exported["complete"] and len(exported["sources"][0]["records"]) == 5
    assert exported["diagnostics"][0]["severity"] == "info"


def test_unavailable_sources_are_explicit_without_fabricating_raw_evidence() -> None:
    md = MapData("unreadable.w3x", "无法读源", all_files=["war3map.w3i", "war3map.wts"])
    record_component_failure(md, "w3i", "war3map.w3i", OSError("read failed"))
    record_component_failure(md, "wts", "war3map.wts", OSError("strings read failed"))
    metadata = json.loads(format_map_metadata_evidence(md))
    strings = json.loads(format_map_string_evidence(md))
    assert (
        metadata["w3i"] is None
        and metadata["source_listed"]
        and not metadata["complete"]
    )
    assert metadata["diagnostics"][0]["message"] == "OSError: read failed"
    assert strings["sources"] == [] and not strings["complete"]
    assert strings["diagnostics"][0]["message"] == "OSError: strings read failed"


@pytest.mark.parametrize("enabled", (True, False))
def test_basic_gate_and_manifest_cover_both_metadata_artifacts(
    tmp_path: Path, enabled: bool
) -> None:
    raw = bytes(_document(31).data)
    md = _load({"war3map.w3i": raw, "war3map.wts": _strings("导出地图")})
    pack = tmp_path / "pack"
    report = write_knowledge_pack_report(
        md,
        str(pack),
        game_data_path=str(tmp_path / "no-game-data"),
        profile=_basic_profile(enabled),
    )
    assert report.status is KnowledgeWriteStatus.COMPLETE
    for filename in ("地图信息证据.json", "地图字符串证据.json"):
        assert (pack / filename).exists() is enabled
        assert (filename in report.items_by_path) is enabled
        if enabled:
            assert report.items_by_path[filename].written
            assert filename in (pack / "资料包目录.tsv").read_text(encoding="utf-8")
    if enabled:
        metadata = json.loads((pack / "地图信息证据.json").read_text(encoding="utf-8"))
        assert _reconstructed_w3i(metadata) == raw
        strings = json.loads((pack / "地图字符串证据.json").read_text(encoding="utf-8"))
        assert strings["sources"][0]["confirmed"][0]["text"] == "导出地图"


def test_campaign_family_exports_each_maps_own_wts_and_w3i_sources(
    tmp_path: Path,
) -> None:
    root = _load({"war3campaign.wts": _strings("战役字符串")}, "campaign.w3n")
    children: list[MapData] = []
    for index, name in enumerate(("第一关", "第二关"), 1):
        children.append(
            _load(
                {
                    "war3map.w3i": bytes(_document(31).data),
                    "war3map.wts": _strings(name),
                },
                f"campaign.w3n::Maps/Chapter{index}.w3x",
            )
        )
    root.sub_maps = children
    pack = tmp_path / "campaign-pack"
    report = write_knowledge_pack_family_report(
        root,
        str(pack),
        game_data_path=str(tmp_path / "no-game-data"),
        profile=_basic_profile(),
    )
    assert report.status is KnowledgeWriteStatus.COMPLETE
    source_files = list(pack.rglob("地图字符串证据.json"))
    metadata_files = list(pack.rglob("地图信息证据.json"))
    assert len(source_files) == len(metadata_files) == 3
    sources = {
        value["map_path"]: value
        for path in source_files
        if (value := json.loads(path.read_text(encoding="utf-8")))
    }
    assert sources["campaign.w3n"]["sources"][0]["member"] == "war3campaign.wts"
    assert sources["campaign.w3n"]["sources"][0]["confirmed"][0]["text"] == "战役字符串"
    for child in children:
        source = sources[child.path]
        assert (
            len(source["sources"]) == 1
            and source["sources"][0]["member"] == "war3map.wts"
        )
        assert source["sources"][0]["confirmed"][0]["text"] == child.name
    metadata = {
        value["map_path"]: value
        for path in metadata_files
        if (value := json.loads(path.read_text(encoding="utf-8")))
    }
    assert metadata["campaign.w3n"]["w3i"] is None
    for child in children:
        assert metadata[child.path]["w3i"]["map_name"] == child.name
    assert sum(item.path.endswith("证据.json") for item in report.items) == 6


def test_partial_nested_tables_keep_their_confirmed_rows_and_partial_boundaries() -> (
    None
):
    d = _document(31)
    raw = bytes(d.data[: d.offsets["item1"] + 6])
    md = _load({"war3map.w3i": raw})
    text = format_map_info(md)
    assert "随机物品表（声明 1 条；已保留 1 条；部分读取）" in text
    assert "集合 #1 · 已保留 1 项 · 部分" in text and "ID='I001'" in text
    exported = json.loads(format_map_metadata_evidence(md))
    assert not exported["w3i"]["random_item_tables"][0]["complete"]
    assert _reconstructed_w3i(exported) == raw


def test_all_game_configurations_are_listed_without_a_false_omission_footer() -> None:
    md = MapData("map.w3x", "配置图")
    md.game_configs = [
        NamedGameConfiguration(
            f"config-{index}.wgc",
            GameConfiguration(1, 0, 1, f"Maps/Map-{index}.w3x", ()),
        )
        for index in range(9)
    ]
    text = format_map_info(md)
    assert "游戏配置：9 个" in text
    for index in range(9):
        assert text.count(f"config-{index}.wgc") == 1
        assert f"Maps/Map-{index}.w3x" in text
    assert "另 " not in text and "……" not in text
