"""攻略报告缓存：键派生、fail-open 读写与段落切片。"""

from pathlib import Path

import pytest

from w3xtool.guide_cache import (
    load_cached_report,
    report_cache_path,
    store_cached_report,
)
from w3xtool.guide_cli import (
    GuideCliOptionError,
    _display_lines,
    parse_guide_cli_options,
)

NL = chr(10)


def _fake_map(tmp_path: Path) -> Path:
    map_file = tmp_path / "demo.w3x"
    map_file.write_bytes(b"PK-demo")
    return map_file


def test_report_cache_roundtrip_and_invalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: 指定缓存目录与一张地图文件。
    monkeypatch.setenv("W3XRAY_CACHE_DIR", str(tmp_path / "cache"))
    map_file = _fake_map(tmp_path)

    # When: 存取同一份报告。
    path = report_cache_path(str(map_file))
    assert path is not None
    report = NL.join(("【基本信息】", "- 地图名：X"))
    store_cached_report(path, report)
    assert load_cached_report(path) == report

    # Then: 地图内容变化后键失效，旧缓存不再命中。
    map_file.write_bytes(b"PK-demo-v2")
    assert report_cache_path(str(map_file)) != path
    assert load_cached_report(report_cache_path(str(map_file))) is None


def test_cache_disabled_via_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: 显式关闭攻略缓存。
    monkeypatch.setenv("W3XRAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("W3XRAY_GUIDE_CACHE", "0")
    map_file = _fake_map(tmp_path)

    # Then: 不派生缓存路径，写入/读取均为无操作。
    assert report_cache_path(str(map_file)) is None
    store_cached_report(None, "text")
    assert load_cached_report(None) is None


def test_load_cached_report_fails_open(tmp_path: Path) -> None:
    # Given: 损坏的缓存文件（非法 UTF-8 字节）。
    corrupt = tmp_path / "corrupt.txt"
    corrupt.write_bytes(bytes((0xFF, 0xFE, 0x00, 0x81)))

    # Then: 损坏或缺失都返回 None，不抛异常。
    assert load_cached_report(corrupt) is None
    assert load_cached_report(tmp_path / "missing.txt") is None


def test_display_lines_slices_single_section() -> None:
    # Given: 三段完整报告。
    full = NL.join(
        (
            "【基本信息】",
            "- 地图名：X",
            "",
            "【任务说明】",
            "- ◆ 主线",
            "  内容",
            "",
            "【英雄阵容】",
            "- 圣骑士(Hpal)",
        )
    )

    # When: 只取任务段。
    picked = _display_lines(full, "quests")

    # Then: 只有该段标题与内容，无跨段泄漏。
    assert picked[0] == "【任务说明】"
    assert "- ◆ 主线" in picked
    assert "基本信息" not in picked
    assert "圣骑士" not in picked


def test_display_lines_without_section_returns_all() -> None:
    # Given: 完整报告。
    full = NL.join(("【基本信息】", "- 地图名：X"))

    # Then: 不切片时原样返回全部行。
    assert _display_lines(full, None) == ["【基本信息】", "- 地图名：X"]


def test_parse_guide_cli_options_supports_refresh() -> None:
    # Given: 带 --refresh 的参数。
    options = parse_guide_cli_options(("t.w3x", "--section", "recipes", "--refresh"))

    # Then: 三项参数都保留。
    assert options.section == "recipes"
    assert options.refresh is True

    # When/Then: 重复 --refresh 报错。
    with pytest.raises(GuideCliOptionError, match="不能重复"):
        parse_guide_cli_options(("t.w3x", "--refresh", "--refresh"))
