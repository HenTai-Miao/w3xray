"""External box ID labels retain complete evidence without becoming map facts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from gametool import local_id_tables as tables_module
from gametool import reference_catalog as reference_module
from gametool.api import GameObject
from gametool.knowledge_object_exports import format_box_id_text
from gametool.local_id_tables import (
    EXTERNAL_ID_STATE,
    LocalIdTableInput,
    LocalIdTableSources,
    load_local_id_tables,
)
from gametool.pack_query_objects import OBJECT_TABLES
from gametool.reference_catalog import load_reference_catalog, search_reference_catalog
from gametool.reference_cli import (
    format_reference_result,
    reference_result_to_dict,
    run_reference_cli,
    write_reference_export,
)
from gametool.reference_models import ReferenceRecord


def _block(code="H001", name="外部名字", description="完整描述", newline="\r\n"):
    return newline.join(
        (f"ID：{code}", f"名字：{name}", f"描述：{description}", "", "")
    )


def _write(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode(encoding)
    path.write_bytes(payload)
    return payload


def _details(record):
    return dict(record.details)


@pytest.mark.parametrize("encoding", ("cp936", "gb18030", "utf-8"))
def test_strict_encodings_keep_multiline_descriptions_and_exact_byte_ranges(
    tmp_path, encoding
):
    first = _block(description="称谓：第一,第二\r\n\r\n第一段\r\n\r\n第二段\ufeff保留")
    if encoding == "cp936":
        first = first.replace("\ufeff", "")
    if encoding == "gb18030":
        first = first.replace("保留", "保留𠀀")
    second = _block("H002", "后续名字", "最后记录", newline="\n")
    path = tmp_path / "单位ID.txt"
    payload = _write(path, first + second, encoding)
    result = load_local_id_tables((path,))
    assert result.complete
    assert [record.id for record in result.records] == ["H001", "H002"]
    assert [record.category for record in result.records] == ["单位", "单位"]
    assert result.sources[0].sha256 == hashlib.sha256(payload).hexdigest()
    offset = 0
    line = 1
    for record, raw in zip(result.records, (first, second)):
        details = _details(record)
        encoded = raw.encode(encoding)
        assert int(details["字节起点"]) == offset
        offset += len(encoded)
        assert int(details["字节终点（不含）"]) == offset
        assert int(details["起始行"]) == line
        line += len(encoded.splitlines())
        assert int(details["结束行"]) == line - 1
        assert record.raw_rows == ((raw, encoded.hex()),)
        assert details["记录SHA-256"] == hashlib.sha256(encoded).hexdigest()
        assert record.state == EXTERNAL_ID_STATE and record.scope == "external"
        assert record.builds == ("unrecorded",)
        assert not record.values and "基础ID" not in details
    assert offset == len(payload)
    assert _details(result.records[0])["描述"] == first.split("描述：", 1)[1]
    assert _details(result.records[0])["编码"] == encoding


def test_only_one_leading_utf8_bom_is_decoded(tmp_path):
    path = tmp_path / "物品ID.txt"
    raw = _block(
        "I001", "\ufeff完整名字", "文本\ufeff内嵌\n名字：属于描述\n描述：仍然属于描述"
    )
    payload = b"\xef\xbb\xbf" + raw.encode("utf-8")
    path.write_bytes(payload)
    result = load_local_id_tables((path,))
    assert result.complete
    record = result.records[0]
    assert record.label == "\ufeff完整名字"
    assert _details(record)["描述"] == raw.split("描述：", 1)[1]
    assert _details(record)["字节起点"] == "3"
    assert record.raw_rows[0][1] == payload[3:].hex()
    assert result.sources[0].sha256 == hashlib.sha256(payload).hexdigest()


def test_existing_box_export_roundtrips_without_reimplementing_writer(tmp_path):
    path = tmp_path / "单位ID.txt"
    obj = GameObject(
        category="单位",
        ext=".w3u",
        obj_id="H001",
        base_id="Hpal",
        is_custom=True,
        name="完整名字",
        fields=[("说明", "多行\n描述"), ("称谓", "头衔一,头衔二")],
    )
    raw = format_box_id_text((obj,), category="单位")
    _write(path, raw)
    imported = load_local_id_tables((path,))
    assert imported.complete
    record = imported.records[0]
    assert record.id == obj.obj_id and record.label == obj.name
    assert _details(record)["描述"] == "称谓：头衔一,头衔二\n\n多行\n描述\n"
    assert record.raw_rows[0][0] == raw


@pytest.mark.parametrize("marker", ("ID：正文标记", "ID：ABCD"))
def test_writer_description_id_prefix_without_declared_roles_is_complete(
    tmp_path, marker
):
    path = tmp_path / "物品ID.txt"
    description = f"第一行\n{marker}\n必须保留的尾段"
    obj = GameObject(
        category="物品",
        ext=".w3t",
        obj_id="I001",
        base_id="ratf",
        is_custom=True,
        name="外部物品",
        fields=[("说明", description)],
    )
    raw = format_box_id_text((obj,), category="物品")
    payload = _write(path, raw)
    imported = load_local_id_tables((path,))
    assert imported.complete and len(imported.records) == 1
    record = imported.records[0]
    assert _details(record)["描述"] == description + "\n"
    assert record.raw_rows == ((raw, payload.hex()),)
    assert search_reference_catalog(imported, "必须保留的尾段").matched == 1


def test_unproved_description_marker_does_not_hide_next_complete_record(tmp_path):
    path = tmp_path / "单位ID.txt"
    first = _block("H001", "第一", "前段\nID：ABCD\n完整尾段")
    second = _block("H002", "第二", "下一记录")
    payload = _write(path, first + second)
    imported = load_local_id_tables((path,))
    assert imported.complete
    assert [record.id for record in imported.records] == ["H001", "H002"]
    assert _details(imported.records[0])["描述"] == "前段\nID：ABCD\n完整尾段\r\n\r\n"
    assert _details(imported.records[1])["记录序号"] == "2"
    assert imported.records[0].raw_rows[0][1] == payload[: len(first.encode())].hex()


def test_existing_text_file_case_variant_reads_same_physical_input(tmp_path):
    path = tmp_path / "custom.txt"
    _write(path, _block())
    variant = path.with_suffix(".TXT")
    if os.name != "nt":
        variant.hardlink_to(path)
    assert path.samefile(variant)
    normal = load_local_id_tables((path,))
    changed_case = load_local_id_tables((variant,))
    assert normal.complete and changed_case.complete
    assert len(normal.records) == len(changed_case.records) == 1
    assert normal.records[0].raw_rows == changed_case.records[0].raw_rows
    assert normal.sources[0].sha256 == changed_case.sources[0].sha256


def test_directory_declared_filename_case_variants_keep_the_same_category(tmp_path):
    path = tmp_path / "单位id.TXT"
    _write(path, _block())
    imported = load_local_id_tables((tmp_path,))
    assert imported.complete and imported.records[0].category == "单位"


@pytest.mark.parametrize("code", ("0000", ' ,|"', "a b ", "éÿab"))
def test_fourcc_validation_preserves_whitespace_and_punctuation_bytes(tmp_path, code):
    path = tmp_path / "技能ID.txt"
    _write(path, _block(code))
    imported = load_local_id_tables((path,))
    assert imported.complete
    assert imported.records[0].id == code


def test_explicit_unknown_filename_stays_unclassified_without_prefix_guessing(tmp_path):
    path = tmp_path / "custom.txt"
    _write(path, _block("hfoo", "这个名字不是分类声明"))
    imported = load_local_id_tables((path,))
    assert imported.complete
    assert imported.records[0].category == ""
    declared = load_local_id_tables((LocalIdTableInput(path, "units"),))
    assert declared.complete and declared.records[0].category == "单位"


def test_source_category_declaration_is_explicit_and_preserved(tmp_path):
    path = tmp_path / "custom.txt"
    preamble = "分类：items\r\n\r\n"
    payload = _write(path, preamble + _block("I001"))
    imported = load_local_id_tables((path,))
    assert imported.complete
    record = imported.records[0]
    assert record.category == "物品"
    assert _details(record)["文件头声明"] == preamble
    assert int(_details(record)["字节起点"]) == len(preamble.encode("utf-8"))
    assert imported.sources[0].sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    ("filename", "explicit", "preamble"),
    (
        ("单位ID.txt", "items", ""),
        ("单位ID.txt", "", "分类：物品\n"),
        ("custom.txt", "unknown", ""),
        ("custom.txt", "", "分类：单位\n类别：单位\n"),
    ),
)
def test_conflicting_unknown_or_duplicate_category_roles_never_choose_a_category(
    tmp_path, filename, explicit, preamble
):
    path = tmp_path / filename
    _write(path, preamble + _block())
    imported = load_local_id_tables((LocalIdTableInput(path, explicit),))
    assert imported.diagnostics
    assert imported.records[0].category == ""
    assert imported.records[0].diagnostics
    assert _details(imported.records[0])["文件头声明"] == preamble


def test_invalid_blocks_keep_full_raw_evidence_and_later_record_ordinals(tmp_path):
    path = tmp_path / "科技ID.txt"
    bad_id = _block("超长ID", "未知记录", "不准丢弃\n\n完整尾部")
    bad_roles = "ID：R001\n名字：第一次\n名字：第二次\n描述：不能猜\n\n"
    valid = _block("R002", "保留的有效记录", "后续完整")
    payload = _write(path, bad_id + bad_roles + valid)
    imported = load_local_id_tables((path,))
    assert [record.id for record in imported.records] == ["R002"]
    assert _details(imported.records[0])["记录序号"] == "3"
    assert len(imported.diagnostics) == 2
    assert bad_id in imported.diagnostics[0]
    assert bad_id.encode().hex() in imported.diagnostics[0]
    assert bad_roles in imported.diagnostics[1]
    assert imported.sources[0].sha256 == hashlib.sha256(payload).hexdigest()


def test_unknown_preamble_and_decode_failures_keep_complete_source_evidence(tmp_path):
    unknown = tmp_path / "单位ID.txt"
    preamble = "无法识别的完整文件头\r\n还有一行\r\n"
    _write(unknown, preamble + _block())
    imported = load_local_id_tables((unknown,))
    assert len(imported.records) == 1 and imported.diagnostics
    assert preamble in imported.diagnostics[0]
    invalid = tmp_path / "物品ID.txt"
    payload = b"\xef\xbb\xbf\xff\x00\xfe"
    invalid.write_bytes(payload)
    rejected = load_local_id_tables((invalid,))
    assert not rejected.records
    assert payload.hex() in rejected.diagnostics[0]
    assert rejected.sources[0].sha256 == hashlib.sha256(payload).hexdigest()


def test_duplicate_and_conflicting_records_stay_ordered_and_case_sensitive(tmp_path):
    path = tmp_path / "物品ID.txt"
    text = (
        _block("I001", "第一")
        + _block("I001", "第一")
        + _block("I001", "竞争名称")
        + _block("i001", "不同ID")
    )
    _write(path, text)
    imported = load_local_id_tables((path, path))
    assert imported.complete
    assert [(record.id, record.label) for record in imported.records] == [
        ("I001", "第一"),
        ("I001", "第一"),
        ("I001", "竞争名称"),
        ("i001", "不同ID"),
    ]
    assert all(
        "名字/描述冲突" in record.diagnostics[0] for record in imported.records[:3]
    )
    assert not imported.records[3].diagnostics


def test_competing_requests_bind_one_original_snapshot_and_no_guessed_category(
    tmp_path, monkeypatch
):
    path = tmp_path / "单位ID.txt"
    _write(path, _block())
    original = tables_module.read_bounded_regular_file
    reads = []

    def record_reads(file, *args, **kwargs):
        reads.append(file)
        return original(file, *args, **kwargs)

    monkeypatch.setattr(tables_module, "read_bounded_regular_file", record_reads)
    imported = load_local_id_tables(
        (path, LocalIdTableInput(path, "units"), LocalIdTableInput(path, "items"))
    )
    assert reads == [path, path]  # One initial snapshot plus its final verification.
    assert len(imported.records) == len(imported.sources) == 1
    assert imported.records[0].category == ""
    assert any("冲突的显式分类参数" in note for note in imported.diagnostics)


def test_duplicate_comparison_keeps_trailing_description_newlines_as_evidence(tmp_path):
    path = tmp_path / "物品ID.txt"
    first = _block("I001", "相同名字", "相同内容")
    second = first.removesuffix("\r\n")
    _write(path, first + second)
    imported = load_local_id_tables((path,))
    assert [dict(record.details)["描述"] for record in imported.records] == [
        "相同内容\r\n\r\n",
        "相同内容\r\n",
    ]
    assert all("描述冲突" in record.diagnostics[0] for record in imported.records)


def test_unselected_duplicate_conflict_diagnostics_survive_limit_and_query(tmp_path):
    path = tmp_path / "单位ID.txt"
    _write(
        path,
        _block("H001", "selected") + _block("H002", "left") + _block("H002", "right"),
    )
    catalog = load_local_id_tables((path,))
    full = search_reference_catalog(catalog)
    limited = search_reference_catalog(catalog, limit=1)
    filtered = search_reference_catalog(catalog, "selected", limit=1)
    assert (
        full.catalog_complete and limited.catalog_complete and filtered.catalog_complete
    )
    assert len(limited.records) == len(filtered.records) == 1
    assert not limited.records[0].diagnostics
    assert limited.diagnostics == filtered.diagnostics == full.diagnostics
    assert any(
        "名字/描述冲突" in note and "H002" in note for note in limited.diagnostics
    )
    rendered = format_reference_result(limited)
    assert "名字/描述冲突" in rendered
    assert "存在不完整/变化来源" not in rendered


def test_directory_traverses_all_declared_files_and_does_not_read_key_text(
    tmp_path, monkeypatch
):
    root = tmp_path / "tables"
    root.mkdir()
    for depth, filename in enumerate(tables_module.BOX_ID_FILENAMES):
        parent = root.joinpath(*(f"d{index}" for index in range(depth)))
        _write(parent / filename, _block(f"X00{depth}"))
    secret = root / "商城key" / "private.txt"
    _write(secret, "THIS_SECRET_MUST_NOT_BE_READ")
    read = tables_module.read_bounded_regular_file

    def never_read_private(path, *args, **kwargs):
        assert path != secret
        return read(path, *args, **kwargs)

    monkeypatch.setattr(tables_module, "read_bounded_regular_file", never_read_private)
    imported = load_local_id_tables((root,))
    assert len(imported.records) == 4
    assert {record.category for record in imported.records} == {
        "单位",
        "技能",
        "物品",
        "科技",
    }
    assert any(
        str(secret) in note and "未导入" in note for note in imported.diagnostics
    )
    assert "THIS_SECRET" not in "\n".join(imported.diagnostics)
    assert str(root) in imported.input_roots


def test_rejects_empty_missing_and_undeclared_file_sources(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    binary = tmp_path / "not-an-id.key"
    binary.write_bytes(b"private-key-not-read")
    for path in (empty, binary, tmp_path / "missing"):
        imported = load_local_id_tables((path,))
        assert not imported.records and imported.diagnostics
        assert "private-key" not in "\n".join(imported.diagnostics)


def _directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(link), str(target)),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("root_link", (False, True))
def test_directory_import_rejects_reparse_paths_before_reading(tmp_path, root_link):
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside / "单位ID.txt", _block())
    root = tmp_path / "input"
    if root_link:
        _directory_link(root, outside)
    else:
        root.mkdir()
        _directory_link(root / "linked", outside)
    imported = load_local_id_tables((root,))
    assert not imported.records
    assert any("reparse" in note for note in imported.diagnostics)
    assert not imported.sources


def test_final_verification_keeps_old_snapshot_hash_when_same_size_bytes_change(
    tmp_path,
):
    path = tmp_path / "单位ID.txt"
    payload = _write(path, _block("H001", "AAAA", "same-size text"))
    sources = LocalIdTableSources((path,))
    metadata = path.stat()
    path.write_bytes(payload.replace(b"AAAA", b"BBBB"))
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    sources.verify()
    imported = sources.catalog()
    assert imported.records[0].label == "AAAA"
    assert imported.sources[0].sha256 == hashlib.sha256(payload).hexdigest()
    assert imported.sources[0].source_file_state == "changed-before-delivery"
    assert any("交付前变化" in note for note in imported.diagnostics)


def test_final_verification_detects_directory_replacement_and_new_sources(tmp_path):
    root = tmp_path / "input"
    path = root / "单位ID.txt"
    payload = _write(path, _block())
    sources = LocalIdTableSources((root,))
    root.rename(tmp_path / "old-input")
    _write(path, payload.decode())
    _write(root / "技能ID.txt", _block("A001"))
    sources.verify()
    assert len(sources.records) == 1
    assert any("完整文件清单" in note for note in sources.diagnostics)
    assert any("来源字节、身份或路径" in note for note in sources.diagnostics)


@pytest.fixture
def tiny_builtins(monkeypatch):
    monkeypatch.setattr(
        reference_module,
        "_base_records",
        lambda: {
            ("单位", "H001"): ReferenceRecord(
                "objects", "H001", "内置单位", "单位", details=(("基础ID", "H001"),)
            ),
        },
    )
    return None


def test_reference_catalog_appends_external_labels_without_base_inheritance(
    tmp_path, tiny_builtins
):
    path = tmp_path / "单位ID.txt"
    _write(path, _block("H001", "同码外部名字", "Alpha\nBeta\n完整长描述"))
    catalog = load_reference_catalog(id_tables=(path,))
    records = [
        record
        for record in catalog.records
        if record.id == "H001" and record.kind == "objects"
    ]
    assert len(records) == 2
    assert [(record.scope, record.label) for record in records] == [
        ("builtin", "内置单位"),
        ("external", "同码外部名字"),
    ]
    external = records[1]
    assert external.state == EXTERNAL_ID_STATE
    assert not external.values and "基础ID" not in _details(external)
    assert any("未覆盖或继承" in note for note in external.diagnostics)
    selected = search_reference_catalog(
        catalog, "Alpha && Beta", kind="objects", source="external", limit=1
    )
    assert selected.matched == 1 and selected.records == (external,)
    assert "完整长描述" in format_reference_result(selected)
    assert (
        reference_result_to_dict(selected)["records"][0]["raw_rows"]
        == external.raw_rows
    )


def test_raw_record_retention_does_not_join_name_and_description_search_fields(
    tmp_path, tiny_builtins
):
    path = tmp_path / "物品ID.txt"
    _write(path, _block("I001", "Alpha", "Beta"))
    catalog = load_reference_catalog(id_tables=(path,))
    assert (
        search_reference_catalog(catalog, "Alpha && Beta", source="external").matched
        == 1
    )
    assert (
        search_reference_catalog(
            catalog, '="Alpha\r\n描述：Beta"', source="external"
        ).matched
        == 0
    )


def test_map_definition_and_external_same_code_remain_separate(tmp_path, tiny_builtins):
    pack = tmp_path / "pack"
    for category in OBJECT_TABLES:
        path = pack / "对象ID" / f"{category}.tsv"
        text = "分类\tID\t数值\t基础ID\t名称\t自定义\t说明\n"
        if category == "单位":
            text += "单位\tH001\t\tH001\t地图名字\t是\t地图完整说明\n"
        _write(path, text)
    _write(pack / "对象字段.tsv", "分类\tID\t名称\t字段键\t字段名\t值\t来源\n")
    table = tmp_path / "单位ID.txt"
    _write(table, _block("H001", "外部名字"))
    catalog = load_reference_catalog(pack, id_tables=(table,))
    same = [
        record
        for record in catalog.records
        if record.kind == "objects" and record.id == "H001"
    ]
    assert [(record.scope, record.label) for record in same] == [
        (str(pack), "地图名字"),
        ("external", "外部名字"),
    ]


def test_limits_keep_complete_records_and_all_rejected_raw_diagnostics(
    tmp_path, tiny_builtins
):
    path = tmp_path / "技能ID.txt"
    tail = "描述尾" * 4000
    invalid = _block("bad", "保留坏块", "坏块全文" * 3000)
    _write(path, _block("A001", "第一", tail) + _block("A002", "第二", tail) + invalid)
    catalog = load_reference_catalog(id_tables=(path,))
    selected = search_reference_catalog(catalog, source="external", limit=1)
    assert selected.matched == 2 and selected.omitted == 1
    assert _details(selected.records[0])["描述"] == tail + "\r\n\r\n"
    assert selected.diagnostics == catalog.diagnostics
    rendered = format_reference_result(selected)
    assert invalid in rendered and tail in rendered


def test_cli_repeated_id_tables_and_export_input_protection(
    tmp_path, tiny_builtins, capsys
):
    root = tmp_path / "external"
    first = root / "单位ID.txt"
    second = tmp_path / "科技ID.txt"
    _write(first, _block("H001", "外部单位"))
    _write(second, _block("R001", "外部科技"))
    exported = tmp_path / "report.json"
    assert (
        run_reference_cli(
            (
                "--id-table",
                str(root),
                "--id-table",
                str(second),
                "--source",
                "external",
                "--json",
                "--export",
                str(exported),
            )
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert [record["id"] for record in report["records"]] == ["H001", "R001"]
    assert json.loads(exported.read_text(encoding="utf-8")) == report
    result = search_reference_catalog(load_reference_catalog(id_tables=(root, second)))
    with pytest.raises(ValueError, match="输入源文件"):
        write_reference_export(first, result)
    with pytest.raises(ValueError, match="只读输入"):
        write_reference_export(root / "report.json", result)
    assert first.read_bytes().startswith("ID：H001".encode())
    assert not (root / "report.json").exists()


@pytest.mark.parametrize("work", ("_metadata_records", "_verify_builtin_sources"))
def test_catalog_revalidates_after_other_source_work(
    tmp_path, tiny_builtins, monkeypatch, work
):
    path = tmp_path / "单位ID.txt"
    payload = _write(path, _block("H001", "AAAA"))
    original_work = getattr(reference_module, work)

    def mutate_after_external_parse(observations):
        path.write_bytes(payload.replace(b"AAAA", b"BBBB"))
        return original_work(observations)

    monkeypatch.setattr(reference_module, work, mutate_after_external_parse)
    catalog = load_reference_catalog(id_tables=(path,))
    external = next(record for record in catalog.records if record.scope == "external")
    assert external.label == "AAAA"
    assert any("交付前变化" in note for note in catalog.diagnostics)
    source = next(source for source in catalog.sources if source.path == str(path))
    assert source.sha256 == hashlib.sha256(payload).hexdigest()
