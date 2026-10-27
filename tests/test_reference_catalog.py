"""Offline references preserve scope, full evidence and truthful build status."""

from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

from gametool import reference_catalog as catalog_module
from gametool.batch_tsv import format_tsv_rows
from gametool.pack_query_objects import OBJECT_TABLES
from gametool.reference_catalog import load_reference_catalog, search_reference_catalog
from gametool.reference_cli import (
    format_reference_result,
    reference_result_to_dict,
    run_reference_cli,
    write_reference_export,
)
from gametool.reference_sources import PackReferenceSources

_HEADER = ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明")
_FIELDS = ("分类", "ID", "名称", "字段键", "字段名", "值", "来源")


def _tsv(path: Path, rows, *, bom: bool = False) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter="\t", lineterminator="\r\n")
    writer.writerows(rows)
    payload = ("\ufeff" if bom else "") + out.getvalue()
    encoded = payload.encode("utf-8")
    path.write_bytes(encoded)
    return encoded


def _pack(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for category in OBJECT_TABLES:
        _tsv(root / "对象ID" / f"{category}.tsv", [_HEADER])
    _tsv(root / "对象字段.tsv", [_FIELDS])
    return root


@pytest.fixture
def small_assets(monkeypatch):
    monkeypatch.setattr(catalog_module, "_LOADED_SOURCE_BASELINES", {})
    monkeypatch.setattr(
        catalog_module.base_objects,
        "BASE_OBJECTS",
        {
            "Same": ("物品", [("生命上限", "75"), ("typed", "base-evidence")]),
            "Only": ("单位", [("生命上限", "900")]),
            "same": ("物品", [("名称", "lower-case")]),
        },
    )
    monkeypatch.setattr(
        catalog_module.base_names,
        "BASE_NAMES",
        {"Same": "基础物品", "Only": "基础单位", "same": "小写物品"},
    )
    monkeypatch.setattr(
        catalog_module.base_names,
        "BASE_NAMES_EN",
        {"Same": "Base Item", "Only": "Base Unit"},
    )
    monkeypatch.setattr(
        catalog_module.base_names, "BASE_CATEGORIES", {"Same": ("神器", "Artifact")}
    )
    return None


def _objects(catalog, *, code="", category=""):
    return [
        record
        for record in catalog.records
        if record.kind == "objects"
        and (not code or record.id == code)
        and (not category or record.category == category)
    ]


def test_builtin_catalog_is_complete_and_retains_definition_aliases(small_assets):
    catalog = load_reference_catalog()
    result = search_reference_catalog(catalog)
    assert catalog.complete
    assert len(result.records) == result.matched == result.total == len(catalog.records)
    assert result.omitted == 0
    assert len(_objects(catalog)) == 3
    field = next(
        record
        for record in catalog.records
        if record.kind == "fields" and record.id == "uhpm"
    )
    assert field.label == "生命上限"
    assert "最大生命值" in field.aliases or len(field.aliases) > 1
    assert dict(field.details)["字段类型"] == catalog_module.fields.field_type("uhpm")
    assert all(len(source.sha256) == 64 for source in catalog.sources)
    assert all(source.build == "unrecorded" for source in catalog.sources)


def test_frozen_assets_hash_all_loaded_data_without_loose_source_files(
    tmp_path, small_assets, monkeypatch
):
    monkeypatch.setattr(
        catalog_module.base_objects, "__file__", str(tmp_path / "frozen-base.pyc")
    )
    catalog = load_reference_catalog()
    source = next(
        source for source in catalog.sources if source.id == "builtin:base_objects"
    )
    payload = json.dumps(
        catalog_module.base_objects.BASE_OBJECTS,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert source.sha256 == hashlib.sha256(payload).hexdigest()
    assert source.fingerprint_basis == "canonical-json-data"
    assert "完整加载数据" in source.provenance
    assert len(_objects(catalog)) == 3


def test_names_only_and_english_only_assets_remain_unclassified_records(
    small_assets, monkeypatch
):
    monkeypatch.setattr(
        catalog_module.base_names,
        "BASE_NAMES",
        {
            "Same": "基础物品",
            "Only": "基础单位",
            "same": "小写物品",
            "N001": "仅有中文名称",
        },
    )
    monkeypatch.setattr(
        catalog_module.base_names, "BASE_NAMES_EN", {"E001": "English-only name"}
    )
    catalog = load_reference_catalog()
    assert len(_objects(catalog)) == 5
    for code in ("N001", "E001"):
        record = _objects(catalog, code=code)[0]
        assert record.category == "" and record.state == "name-only"
        assert not record.values
        assert dict(record.details).get("基础ID") is None
    assert (
        search_reference_catalog(catalog, "English-only", kind="objects").records[0].id
        == "E001"
    )


def test_category_case_identity_and_custom_field_precedence(tmp_path, small_assets):
    pack = _pack(tmp_path / "pack")
    _tsv(
        pack / "对象ID" / "物品.tsv",
        [_HEADER, ("物品", "Same", "", "Same", "自定义物品", "是", "说明完整")],
    )
    _tsv(
        pack / "对象ID" / "单位.tsv",
        [_HEADER, ("单位", "Same", "", "", "同码单位", "是", "")],
    )
    _tsv(
        pack / "对象字段.tsv",
        [
            _FIELDS,
            ("物品", "Same", "字段别名", "uhpm", "生命上限", "", "war3map.w3t"),
            ("单位", "Same", "单位别名", "ustr", "力量", "001.0", "war3map.w3u"),
        ],
    )
    catalog = load_reference_catalog(pack)
    assert catalog.complete
    item = _objects(catalog, code="Same", category="物品")[0]
    unit = _objects(catalog, code="Same", category="单位")[0]
    assert item.label == "自定义物品" and "字段别名" in item.aliases
    assert item.values[0].value == ""  # Explicit empty custom values remain overrides.
    assert item.values[1].state == "overridden-base"
    assert unit.label == "同码单位"
    assert len(unit.values) == 1 and unit.values[0].value == "001.0"
    assert "Base Item" not in unit.aliases
    assert _objects(catalog, code="same")[0].label == "小写物品"
    exact = search_reference_catalog(catalog, '="Same"', kind="objects")
    assert {record.id for record in exact.records} == {"Same"}
    items = search_reference_catalog(catalog, category="items", kind="objects")
    assert all(record.category == "物品" for record in items.records)


def test_field_only_sparse_bom_quoted_and_reversible_cells(tmp_path, small_assets):
    pack = _pack(tmp_path / "pack")
    payload_text = 'first\tfield\r\nsecond "quoted"\n\ufeffembedded' + "尾" * 100001
    rows = [
        _FIELDS + ("原始扩展",),
        (
            "单位",
            "Only",
            "全名\n别名",
            "uhpm",
            "生命上限",
            payload_text,
            "source\r\ncontext",
            "'literal-prefix\twhole",
        ),
    ]
    field_path = pack / "对象字段.tsv"
    field_path.write_bytes(b"\xef\xbb\xbf" + format_tsv_rows(rows).encode("utf-8"))
    # Quoted first cells and sparse declared headers go through the common schema.
    _tsv(
        pack / "对象ID" / "单位.tsv",
        [
            _HEADER + tuple(f"extra-{index}" for index in range(1200)),
            ("单位", "U001", "", "", "稀疏单位"),
        ],
        bom=True,
    )
    catalog = load_reference_catalog(pack)
    record = _objects(catalog, code="Only", category="单位")[0]
    assert record.state == "field-only"
    assert dict(record.details)["基础ID"] == ""
    assert len(record.values) == 1  # No guessed base inheritance for a field-only ID.
    assert record.values[0].value == payload_text
    assert record.values[0].extras == (("原始扩展", "'literal-prefix\twhole"),)
    sparse = _objects(catalog, code="U001")[0]
    assert len(sparse.raw_rows[0]) == 7
    source = next(
        source for source in catalog.sources if source.path == str(field_path)
    )
    assert source.sha256 == hashlib.sha256(field_path.read_bytes()).hexdigest()
    result = search_reference_catalog(catalog, "尾尾尾", kind="objects")
    serialized = json.dumps(reference_result_to_dict(result), ensure_ascii=False)
    assert "尾" * 100001 in serialized


def test_boolean_matches_boundaries_and_limit_selects_whole_records(
    tmp_path, small_assets
):
    pack = _pack(tmp_path / "pack")
    _tsv(
        pack / "对象字段.tsv",
        [
            _FIELDS,
            ("技能", "A001", "first", "key1", "north", "north", "origin"),
            ("技能", "A001", "second", "key2", "south", "south", "origin"),
            ("技能", "A002", "another", "key1", "north", "north", "origin"),
        ],
    )
    catalog = load_reference_catalog(pack)
    combined = search_reference_catalog(catalog, "north && south", kind="objects")
    assert [record.id for record in combined.records] == ["A001"]
    assert not search_reference_catalog(catalog, "north%south", kind="objects").records
    limited = search_reference_catalog(catalog, "north", kind="objects", limit=1)
    assert limited.matched == 2 and limited.omitted == 1
    assert len(limited.records[0].values) == 2
    assert "另 1 条匹配未显示" in format_reference_result(limited)
    for bad in (-1, True, 0.5, "1"):
        with pytest.raises(ValueError, match="非负整数"):
            search_reference_catalog(catalog, limit=cast(int, bad))


def test_ambiguous_schema_and_diagnostic_only_campaign_children_survive_limit(
    tmp_path, small_assets
):
    pack = _pack(tmp_path / "campaign")
    child = pack / "子地图" / "002-child"
    child.mkdir(parents=True)
    _tsv(
        child / "对象字段.tsv",
        [
            ("分类", "ID", "字段键", "key", "值"),
            ("单位", "U002", "uhpm", "umpm", "100"),
        ],
    )
    result = search_reference_catalog(
        load_reference_catalog(pack), kind="objects", limit=1
    )
    assert not result.catalog_complete
    assert any(
        "重复语义列" in note and "002-child" in note for note in result.diagnostics
    )
    assert any(
        "未记录此表" in note and "002-child" in note for note in result.diagnostics
    )
    assert result.omitted > 0
    assert all(note in format_reference_result(result) for note in result.diagnostics)


def test_source_bytes_refresh_even_with_same_size_and_timestamp(tmp_path, small_assets):
    pack = _pack(tmp_path / "pack")
    path = pack / "对象字段.tsv"
    _tsv(path, [_FIELDS, ("单位", "U001", "one", "uhpm", "生命上限", "123", "origin")])
    first = load_reference_catalog(pack)
    before = path.stat()
    path.write_bytes(path.read_bytes().replace(b"123", b"456"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    second = load_reference_catalog(pack)
    assert _objects(first, code="U001")[0].values[0].value == "123"
    assert _objects(second, code="U001")[0].values[0].value == "456"
    assert next(
        source.sha256 for source in first.sources if source.path == str(path)
    ) != next(source.sha256 for source in second.sources if source.path == str(path))


def test_source_changed_during_load_preserves_confirmed_records_and_diagnostics(
    tmp_path, small_assets, monkeypatch
):
    pack = _pack(tmp_path / "pack")
    path = pack / "对象字段.tsv"
    _tsv(path, [_FIELDS, ("单位", "U001", "unit", "uhpm", "生命上限", "123", "origin")])
    verify = PackReferenceSources.verify

    def changed(adapter):
        path.write_bytes(path.read_bytes().replace(b"123", b"456"))
        verify(adapter)

    monkeypatch.setattr(PackReferenceSources, "verify", changed)
    catalog = load_reference_catalog(pack)
    assert not catalog.complete
    assert _objects(catalog, code="U001")[0].values[0].value == "123"
    assert any("交付前变化" in note for note in catalog.diagnostics)


def test_builtin_loaded_data_hash_does_not_adopt_changed_disk_source_hash(
    tmp_path, small_assets, monkeypatch
):
    path = tmp_path / "base_objects.py"
    path.write_text(
        "BASE_OBJECTS = {'U001': ('单位', [('name', 'old')])}\n", encoding="utf-8"
    )
    loaded = {"U001": ("单位", [("name", "old")])}
    monkeypatch.setattr(catalog_module.base_objects, "__file__", str(path))
    monkeypatch.setattr(catalog_module.base_objects, "BASE_OBJECTS", loaded)
    first = load_reference_catalog()
    path.write_text(
        "BASE_OBJECTS = {'U001': ('单位', [('name', 'new')])}\n", encoding="utf-8"
    )
    second = load_reference_catalog()
    old_source = next(
        source for source in first.sources if source.id == "builtin:base_objects"
    )
    new_source = next(
        source for source in second.sources if source.id == "builtin:base_objects"
    )
    assert _objects(second, code="U001")[0].values[0].value == "old"
    assert new_source.sha256 == old_source.sha256
    assert new_source.fingerprint_basis == "canonical-json-data"
    assert (
        new_source.source_file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert new_source.source_file_sha256 != old_source.source_file_sha256
    assert new_source.source_file_state == "changed-since-loaded-data"
    assert not second.complete
    assert any(
        "同一已加载数据指纹下磁盘源码已变化" in note for note in second.diagnostics
    )
    assert "未证明其版本与已加载数据一致" in new_source.provenance


def test_builtin_disk_change_before_delivery_is_explicit_incomplete_evidence(
    tmp_path, small_assets, monkeypatch
):
    path = tmp_path / "base_objects.py"
    path.write_text("synthetic old source\n", encoding="utf-8")
    monkeypatch.setattr(catalog_module.base_objects, "__file__", str(path))
    metadata = catalog_module._metadata_records

    def changed(observations):
        path.write_text("synthetic new source\n", encoding="utf-8")
        return metadata(observations)

    monkeypatch.setattr(catalog_module, "_metadata_records", changed)
    result = load_reference_catalog()
    assert not result.complete
    assert any("磁盘源码的独立观测在交付前变化" in note for note in result.diagnostics)


def test_removed_loose_source_is_not_reclassified_as_never_present_frozen_data(
    tmp_path, small_assets, monkeypatch
):
    path = tmp_path / "base_objects.py"
    path.write_text("synthetic previously present source\n", encoding="utf-8")
    monkeypatch.setattr(catalog_module.base_objects, "__file__", str(path))
    before = load_reference_catalog()
    path.unlink()
    after = load_reference_catalog()
    old = next(
        source for source in before.sources if source.id == "builtin:base_objects"
    )
    new = next(
        source for source in after.sources if source.id == "builtin:base_objects"
    )
    assert new.sha256 == old.sha256
    assert old.source_file_sha256 and not new.source_file_sha256
    assert new.source_file_state == "missing-since-loaded-data"
    assert "内嵌/PYZ" not in new.provenance
    assert not after.complete
    assert any(
        "同一已加载数据指纹下磁盘源码已变化或不可读取" in note
        for note in after.diagnostics
    )


def test_field_table_is_parsed_once_for_all_categories(
    tmp_path, small_assets, monkeypatch
):
    import gametool.reference_sources as source_module

    pack = _pack(tmp_path / "pack")
    calls = []
    parse = source_module.object_field_table

    def observed(raw):
        calls.append(raw)
        return parse(raw)

    monkeypatch.setattr(source_module, "object_field_table", observed)
    load_reference_catalog(pack)
    assert len(calls) == 1


def test_csv_failure_retains_confirmed_records_and_source_diagnostics(
    tmp_path, small_assets, monkeypatch
):
    import gametool.reference_sources as source_module

    pack = _pack(tmp_path / "pack")
    original = source_module.csv.reader

    def rows_then_error(lines, **kwargs):
        text = lines.getvalue()
        if "字段键" not in text:
            yield from original(lines, **kwargs)
            return
        yield list(_FIELDS)
        yield ["单位", "U123", "confirmed", "uhpm", "生命上限", "42", "origin"]
        raise csv.Error("synthetic parser failure")

    monkeypatch.setattr(source_module.csv, "reader", rows_then_error)
    catalog = load_reference_catalog(pack)
    assert _objects(catalog, code="U123")[0].values[0].value == "42"
    assert not catalog.complete
    assert any("保留此前 2 条逻辑记录" in note for note in catalog.diagnostics)


@pytest.mark.parametrize("table", ["fields", "objects"])
def test_unterminated_quoted_record_is_incomplete_without_confirming_swallowed_rows(
    tmp_path, small_assets, table
):
    pack = _pack(tmp_path / "pack")
    path = pack / "对象字段.tsv" if table == "fields" else pack / "对象ID" / "单位.tsv"
    header = _FIELDS if table == "fields" else _HEADER
    confirmed = (
        ("单位", "U000", "confirmed", "uhpm", "生命上限", "42", "fixture")
        if table == "fields"
        else ("单位", "U000", "", "", "confirmed", "是", "known")
    )
    _tsv(path, [header, confirmed])
    with path.open("ab") as handle:
        handle.write(
            (
                '单位\tU001\tbroken\tuhpm\t生命上限\t"unterminated\n'
                "单位\tU002\tlater\tuhpm\t生命上限\t44\tfixture\n"
            ).encode("utf-8")
        )
    result = load_reference_catalog(pack)
    assert _objects(result, code="U000")
    assert not _objects(result, code="U001") and not _objects(result, code="U002")
    assert not result.complete
    notes = [
        note
        for note in result.diagnostics
        if str(path) in note and "TSV 解析失败" in note
    ]
    assert len(notes) == 1
    assert "失败逻辑记录序号 3" in notes[0]
    assert "物理行 3..4" in notes[0]
    assert "unexpected end of data" in notes[0]


def test_source_filter_matches_declared_value_provenance_and_version_origin(
    tmp_path, small_assets
):
    pack = _pack(tmp_path / "pack")
    _tsv(
        pack / "对象字段.tsv",
        [
            _FIELDS,
            (
                "单位",
                "U001",
                "unit",
                "uhpm",
                "生命上限",
                "123",
                "independent-source-label",
            ),
        ],
    )
    catalog = load_reference_catalog(pack)
    result = search_reference_catalog(
        catalog, kind="objects", source="independent-source-label"
    )
    assert [record.id for record in result.records] == ["U001"]
    version_source = next(
        record
        for record in catalog.records
        if record.kind == "versions" and record.state == "rva-table"
    )
    origin = dict(version_source.details)["来源"]
    assert search_reference_catalog(catalog, kind="versions", source=origin).records


def test_version_qualifications_and_unknown_build_recovery(small_assets):
    catalog = load_reference_catalog()
    versions = search_reference_catalog(catalog, kind="versions")
    assert {record.state for record in versions.records} >= {
        "exact",
        "rva-table",
        "template",
        "reforged-pending",
    }
    exact = search_reference_catalog(catalog, build="1.27.0.52240")
    assert exact.records and all(record.kind == "versions" for record in exact.records)
    assert all(
        record.coverage is not None and record.coverage["runtime_verified"] is False
        for record in versions.records
    )
    unknown = search_reference_catalog(catalog, build="0.0.0.0")
    assert not unknown.records
    assert any(
        "未记录 build" in note and "unrecorded" in note for note in unknown.recovery
    )


def test_family_template_coverage_preserves_identity_without_concrete_validation(
    small_assets, monkeypatch
):
    inspected = []
    inspect = catalog_module.inspect_profile_support

    def concrete_only(data):
        assert data["game_version"]
        inspected.append(data["game_version"])
        return inspect(data)

    monkeypatch.setattr(catalog_module, "inspect_profile_support", concrete_only)
    catalog = load_reference_catalog()
    templates = [
        record
        for record in catalog.records
        if record.kind == "versions"
        and record.id in {"classic-template", "reforged-pending"}
    ]
    assert len(templates) == 2 and inspected
    for record in templates:
        coverage = record.coverage
        assert coverage is not None
        details = dict(record.details)
        assert coverage["game_version"] == ""
        assert coverage["engine"] == details["engine"]
        assert coverage["arch"] == details["arch"]
        assert coverage["tier"] == record.state
        assert coverage["source"] == details["来源"] and coverage["source"]
        assert coverage["declaration_kind"] == "family-template"
        assert coverage["concrete_build"] is False
        assert coverage["complete"] is True
        assert coverage["runtime_verified"] is False and coverage["supported"] is False
        assert not any("需要四段数字版本号" in note for note in record.diagnostics)


def test_builtin_profile_data_hash_includes_family_declarations(
    small_assets, monkeypatch
):
    first = load_reference_catalog()
    resolve = catalog_module.live_handle_chain.resolve_profile

    def changed_family(version, engine="classic", arch="x86"):
        profile = resolve(version, engine, arch)
        return (
            replace(profile, source=profile.source + " synthetic template revision")
            if version is None
            else profile
        )

    monkeypatch.setattr(
        catalog_module.live_handle_chain, "resolve_profile", changed_family
    )
    second = load_reference_catalog()
    source_before = next(
        source for source in first.sources if source.id == "builtin:live_profiles"
    )
    source_after = next(
        source for source in second.sources if source.id == "builtin:live_profiles"
    )
    assert source_before.source_file_sha256 == source_after.source_file_sha256
    assert source_before.sha256 != source_after.sha256
    templates = [
        record
        for record in second.records
        if record.kind == "versions"
        and record.id in {"classic-template", "reforged-pending"}
    ]
    assert len(templates) == 2
    assert all(
        "synthetic template revision" in dict(record.details)["来源"]
        for record in templates
    )


def _profile() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "game_version": "9.8.7.6",
        "engine": "reforged",
        "arch": "x64",
        "tier": "reforged-pending",
        "source": "synthetic independently declared",
        "field_layouts": [
            {
                "scope": "unit",
                "key": "hp",
                "type": "f32",
                "offset": 256,
                "source": "synthetic fixture",
                "evidence": "declared-layout-only",
            }
        ],
    }


def test_profile_json_is_pure_qualified_and_hashed(tmp_path, small_assets):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")
    catalog = load_reference_catalog(profile_json=path)
    selected = search_reference_catalog(catalog, kind="versions", build="9.8.7.6")
    assert len(selected.records) == 1
    record = selected.records[0]
    assert record.state == "reforged-pending"
    assert record.values[0].key == "unit.hp"
    assert record.values[0].state == "declared-layout-only"
    assert record.coverage is not None
    assert record.coverage["runtime_verified"] is False
    source = next(source for source in selected.sources if source.path == str(path))
    assert source.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert source.build == "9.8.7.6"


def test_cli_profile_errors_help_tuple_and_complete_exports(
    tmp_path, small_assets, capsys
):
    assert run_reference_cli(("--help",)) == 0
    assert "--profile-json" in capsys.readouterr().out
    profile = _profile()
    profile["field_layouts"][0]["offset"] = True
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    assert run_reference_cli(("--profile-json", str(path), "--kind", "versions")) == 2
    assert "整数" in capsys.readouterr().err
    path.write_text(
        '{"game_version":"1.2.3.4","game_version":"2.3.4.5"}', encoding="utf-8"
    )
    assert run_reference_cli(("--profile-json", str(path))) == 2
    assert "重复键" in capsys.readouterr().err
    exported = tmp_path / "reference.json"
    assert (
        run_reference_cli(("--kind", "versions", "--json", "--export", str(exported)))
        == 0
    )
    stdout = json.loads(capsys.readouterr().out)
    assert json.loads(exported.read_text(encoding="utf-8")) == stdout
    assert stdout["omitted"] == 0 and len(stdout["records"]) == stdout["matched"]


def test_exports_cannot_replace_input_or_write_inside_pack(tmp_path, small_assets):
    pack = _pack(tmp_path / "pack")
    result = search_reference_catalog(
        load_reference_catalog(pack), kind="objects", limit=1
    )
    with pytest.raises(ValueError, match="输入源文件"):
        write_reference_export(pack / "对象字段.tsv", result)
    with pytest.raises(ValueError, match="只读输入"):
        write_reference_export(pack / "report.md", result)
    path = tmp_path / "report.md"
    write_reference_export(path, result)
    assert path.read_text(encoding="utf-8") == format_reference_result(result)


def test_source_filter_uses_exact_source_identity_and_all_diagnostics(small_assets):
    catalog = load_reference_catalog()
    source = next(
        source for source in catalog.sources if source.id == "builtin:base_objects"
    )
    selected = search_reference_catalog(catalog, source=source.sha256)
    assert selected.records and all(
        "builtin:base_objects" in record.sources for record in selected.records
    )
    partial = search_reference_catalog(
        replace(catalog, diagnostics=("all original diagnostics",)), limit=1
    )
    assert partial.diagnostics == ("all original diagnostics",)
    assert "all original diagnostics" in format_reference_result(partial)
