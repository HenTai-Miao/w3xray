"""Validated base-object description cache contracts."""

from __future__ import annotations

import csv
from pathlib import Path

from w3xtool.description_cache import (
    build_description_cache_from_batch,
    format_description_cache_tsv,
    load_description_cache,
)


_LEGACY_HEADER = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)


def test_batch_cache_accepts_only_owned_unique_base_client_fill_rows(tmp_path: Path) -> None:
    # Given: one owned report mixes a proven base fill with unsafe rows.
    report = _owned_report(tmp_path, "001_base", "a" * 64)
    _write_rows(
        report,
        (
            _LEGACY_HEADER,
            _legacy_row("ratf", "ratf", "否", "客户端补全", "基础提示", "完整说明"),
            _legacy_row("I001", "ratf", "是", "客户端补全", "自定义提示", "自定义说明"),
            _legacy_row("rde1", "rde1", "否", "地图原值", "地图提示", "地图说明"),
        ),
    )

    # When: cache evidence is discovered from the batch root.
    cache = build_description_cache_from_batch(tmp_path)

    # Then: only the original base object's client fill is usable.
    assert [entry.raw_value for entry in cache.lookup("物品", "ratf", "基础提示", None)] == [
        "基础提示",
    ]
    assert [entry.raw_value for entry in cache.lookup("物品", "ratf", "扩展提示", None)] == [
        "完整说明",
    ]
    assert cache.lookup("物品", "rde1", "扩展提示", None) == ()
    assert cache.conflict_count == 0


def test_batch_cache_removes_a_key_when_owned_sources_disagree(tmp_path: Path) -> None:
    # Given: two valid owned base reports disagree byte-for-byte on one key.
    first = _owned_report(tmp_path, "001_first", "b" * 64)
    second = _owned_report(tmp_path, "002_second", "c" * 64)
    _write_rows(first, (_LEGACY_HEADER, _legacy_row("ratf", "ratf", "否", "客户端补全", "提示", "甲")))
    _write_rows(second, (_LEGACY_HEADER, _legacy_row("ratf", "ratf", "否", "客户端补全", "提示", "乙")))

    # When: the cache is built.
    cache = build_description_cache_from_batch(tmp_path)

    # Then: the conflicting description key is absent and audited once.
    assert cache.lookup("物品", "ratf", "扩展提示", None) == ()
    assert cache.conflict_count == 1
    assert any("物品/ratf/扩展提示" in diagnostic for diagnostic in cache.diagnostics)


def test_unowned_malformed_and_symlink_reports_are_never_cache_sources(tmp_path: Path) -> None:
    # Given: an unowned report, an invalid marker, and a symlink to a valid report.
    unowned = tmp_path / "unowned" / "对象描述.tsv"
    unowned.parent.mkdir()
    _write_rows(unowned, (_LEGACY_HEADER, _legacy_row("ratf", "ratf", "否", "客户端补全", "提示", "说明")))
    invalid = _owned_report(tmp_path, "invalid", "not-a-digest")
    _write_rows(invalid, (_LEGACY_HEADER, _legacy_row("ratf", "ratf", "否", "客户端补全", "提示", "说明")))
    valid = _owned_report(tmp_path, "valid", "d" * 64)
    _write_rows(valid, (_LEGACY_HEADER, _legacy_row("ratf", "ratf", "否", "客户端补全", "提示", "说明")))
    linked_directory = tmp_path / "地图" / "linked"
    linked_directory.mkdir()
    (linked_directory / ".w3xray-batch-owned").write_text("f" * 64, encoding="ascii")
    linked = linked_directory / "对象描述.tsv"
    linked.symlink_to(valid)

    # When: only the fixed report name is discovered and parsed.
    cache = build_description_cache_from_batch(tmp_path)

    # Then: exactly the regular, owned report contributes evidence.
    assert len(cache.lookup("物品", "ratf", "扩展提示", None)) == 1


def test_formatted_cache_round_trips_tabs_newlines_quotes_and_leading_space(tmp_path: Path) -> None:
    # Given: an owned v2 row with raw whitespace and embedded TSV control characters.
    report = _owned_report(tmp_path, "001_v2", "e" * 64)
    raw = '  "开头\t正文\r\n第二行  '
    _write_rows(
        report,
        (
            (
                "分类", "对象ID", "基础ID", "名称", "自定义", "文本角色", "字段键", "字段标签",
                "等级/变体", "原始全文", "可读全文", "来源类型", "来源路径", "状态", "占位",
                "冲突组", "证据序号",
            ),
            (
                "物品", "ratf", "ratf", "戒指", "否", "扩展提示", "utub", "提示文本", "",
                raw, raw, "客户端", "Units\\ItemStrings.txt", "客户端补全", "否", "", "1",
            ),
        ),
    )
    cache = build_description_cache_from_batch(tmp_path)
    path = tmp_path / "可信描述缓存.tsv"
    path.write_text(format_description_cache_tsv(cache), encoding="utf-8", newline="")

    # When: the standalone trusted cache is loaded again.
    loaded = load_description_cache(str(path))

    # Then: standard TSV parsing returns the exact raw value.
    assert loaded.lookup("物品", "ratf", "扩展提示", None)[0].raw_value == raw


def _owned_report(root: Path, name: str, digest: str) -> Path:
    directory = root / "地图" / name
    directory.mkdir(parents=True)
    (directory / ".w3xray-batch-owned").write_text(digest, encoding="ascii")
    return directory / "对象描述.tsv"


def _write_rows(path: Path, rows: tuple[tuple[str, ...], ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def _legacy_row(
    object_id: str,
    base_id: str,
    custom: str,
    state: str,
    tip: str,
    description: str,
) -> tuple[str, ...]:
    return (
        "物品", object_id, base_id, object_id, custom, "", tip, tip, f"base:{base_id}",
        description, description, f"base:{base_id}", state,
    )
