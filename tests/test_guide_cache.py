"""攻略报告缓存：键派生、fail-open 读写与段落切片。"""

import os
from pathlib import Path

import pytest

from gametool.guide_cache import (
    load_cached_report,
    report_cache_path,
    store_cached_report,
)
from gametool.guide_cli import (
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
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "cache"))
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
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("GAMEXRAY_GUIDE_CACHE", "0")
    map_file = _fake_map(tmp_path)

    # Then: 不派生缓存路径，写入/读取均为无操作。
    assert report_cache_path(str(map_file)) is None
    store_cached_report(None, "text")
    assert load_cached_report(None) is None


def test_same_size_content_change_with_restored_mtime_invalidates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "cache"))
    source = _fake_map(tmp_path)
    before = source.stat()
    old_path = report_cache_path(str(source))
    store_cached_report(old_path, "old source report")
    source.write_bytes(b"PK-next")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    assert report_cache_path(str(source)) != old_path
    assert load_cached_report(report_cache_path(str(source))) is None
    assert load_cached_report(old_path) == "old source report"


def test_cached_cli_report_revalidates_source_before_printing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gametool import guide_cli

    source = _fake_map(tmp_path)
    old_path = report_cache_path(str(source))
    store_cached_report(old_path, "MUST-NOT-DELIVER-OLD-REPORT")
    original = guide_cli.load_cached_report

    def change_after_cache_read(path):
        text = original(path)
        source.write_bytes(b"PK-next")
        return text

    monkeypatch.setattr(guide_cli, "load_cached_report", change_after_cache_read)
    assert guide_cli.run_guide_cli(guide_cli.GuideCliOptions(str(source))) == 2
    result = capsys.readouterr()
    assert "MUST-NOT-DELIVER" not in result.out
    assert "来源" in result.err and "变化" in result.err


@pytest.mark.parametrize("change_during_report", (False, True))
def test_cli_never_publishes_old_loaded_map_under_a_new_source_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change_during_report: bool,
) -> None:
    from gametool import guide_cli
    from gametool.gui_offline_acceptance_support import _fixture_mpq
    from gametool.map_loader import load_map

    source = tmp_path / "changing.w3x"
    original = _fixture_mpq({"war3map.j": b"// old source"})
    changed = _fixture_mpq({"war3map.j": b"// new source"})
    source.write_bytes(original)
    before = source.stat()
    loaded = load_map(str(source))
    old_cache = report_cache_path(str(source))

    def change_source() -> None:
        source.write_bytes(changed)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

    if not change_during_report:
        change_source()
    monkeypatch.setattr(guide_cli, "load_map", lambda *_args, **_kwargs: loaded)

    def old_report(*_args):
        change_source()
        return "MUST-NOT-PUBLISH-OLD-MAP"

    monkeypatch.setattr(guide_cli, "format_guide_report", old_report)
    assert guide_cli.run_guide_cli(guide_cli.GuideCliOptions(str(source))) == 2
    assert loaded._closed
    assert load_cached_report(old_cache) is None
    assert load_cached_report(report_cache_path(str(source))) is None
    assert "MUST-NOT-PUBLISH" not in capsys.readouterr().out


def test_new_report_semantics_do_not_reuse_the_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import guide_cache

    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(tmp_path / "cache"))
    map_file = _fake_map(tmp_path)
    current = report_cache_path(str(map_file))
    assert guide_cache.GUIDE_CACHE_VERSION == "guide-v43"
    with monkeypatch.context() as older:
        older.setattr(guide_cache, "GUIDE_CACHE_VERSION", "guide-v" + str(42))
        previous = report_cache_path(str(map_file))
        store_cached_report(previous, "previous report evidence")
    assert current != previous and load_cached_report(current) is None
    assert load_cached_report(previous) == "previous report evidence"


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
