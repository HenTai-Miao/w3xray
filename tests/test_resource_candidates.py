"""Only current source reads confirm full, source-declared resource paths."""

from collections import Counter
from contextlib import nullcontext
import csv
import hashlib
from io import StringIO
from pathlib import Path

import pytest

from gametool import resource_candidates as candidates
from gametool import resource_candidate_sources as directory_sources
from gametool.audit import build_audit_report
from gametool.archive_source import PathArchiveSource
from gametool.batch_tsv import decode_tsv_cell
from gametool.map_data import MapData
from gametool.mpq import MPQArchive
from gametool.resource_candidate_sources import (
    ResourceDirectorySource,
    ResourcePathConflict,
)
from gametool.resource_content_refs import build_resource_content_references
from gametool.resources import build_resource_report, find_resource_paths
from tests.test_mpq_names_locale import build_archive_bytes


class _Reader:
    def __init__(self, files: dict[str, bytes | Exception]) -> None:
        self.files = files
        self.reads: Counter[str] = Counter()
        self.verifications = 0

    def read_file(self, name: str) -> bytes:
        self.reads[name] += 1
        value = self.files[name]
        if isinstance(value, Exception):
            raise value
        return value

    def verify_source(self) -> None:
        self.verifications += 1


def _map(script: str = "", *, source: str = "war3map.j") -> MapData:
    return MapData(
        path="synthetic-resources.w3x",
        name="资源",
        scripts={source: script} if script else {},
    )


def _probe(monkeypatch: pytest.MonkeyPatch, reader: _Reader, md: MapData):
    monkeypatch.setattr(candidates, "open_map_source", lambda _md: nullcontext(reader))
    return candidates.build_resource_candidate_report(md)


def _quoted(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def test_unicode_long_paths_and_duplicate_origins_share_actual_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "素材\\" + "完整路径" * 320 + ";特效(二).mdx"
    script = "call Preload(" + _quoted(path) + ")\ncall Preload(" + _quoted(path) + ")"
    md = _map(script)
    reader = _Reader({path: b"MDLXpayload"})
    report = _probe(monkeypatch, reader, md)
    assert len(report.items) == 2 and report.confirmed_paths == (path,)
    assert reader.reads == {path: 1} and reader.verifications == 2
    for item in report.items:
        assert item.value == path and item.state == "confirmed" and item.size == 11
        assert script[item.offset : item.end_offset] == item.raw
        assert item.language == "JASS" and item.binding.startswith("Preload:")
        assert item.source_fingerprint.startswith("decoded-text-sha256:")
    assert md.all_files == [] and md.scripts["war3map.j"] == script


@pytest.mark.parametrize(
    "source,lua,comment", [("war3map.j", False, "//"), ("war3map.lua", True, "--")]
)
def test_comments_and_prose_never_become_script_path_candidates(
    monkeypatch: pytest.MonkeyPatch, source: str, lua: bool, comment: str
) -> None:
    script = (
        comment
        + ' "hidden.blp"\n'
        + ("local n=12 // 3\n" if lua else "")
        + 'Preload("actual.blp")'
    )
    md = _map(script, source=source)
    reader = _Reader({"actual.blp": b""})
    report = _probe(monkeypatch, reader, md)
    assert [(item.path, item.state, item.size) for item in report.items] == [
        ("actual.blp", "confirmed", 0)
    ]
    assert reader.reads == {"actual.blp": 1}
    refs = build_resource_report(md)
    assert "actual.blp" in refs.by_path and "hidden.blp" not in refs.by_path


def test_lua_long_brackets_preserve_literal_offsets_and_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "资源\\动画.blp"
    script = '--[==[ "comment.blp" ]==]\nlocal value=[==[\n' + path + "]==]"
    report = _probe(
        monkeypatch, _Reader({path: b"BLP2"}), _map(script, source="war3map.lua")
    )
    (item,) = report.items
    assert item.path == path and item.language == "Lua" and item.state == "confirmed"
    assert script[item.offset : item.end_offset] == item.raw


@pytest.mark.parametrize(
    "expression",
    ['"fragment.blp" + suffix', 'prefix + ".blp"', '"fragment.blp" .. suffix'],
)
def test_dynamic_path_fragments_remain_unknown_and_are_not_probed(
    monkeypatch: pytest.MonkeyPatch, expression: str
) -> None:
    reader = _Reader({"fragment.blp": b"fake", ".blp": b"fake"})
    report = _probe(monkeypatch, reader, _map("call Preload(" + expression + ")"))
    assert report.items and {item.state for item in report.items} == {"unknown"}
    assert not reader.reads and not report.confirmed_paths
    assert "拼接" in report.items[0].diagnostics[0]


@pytest.mark.parametrize(
    "expression",
    [
        '("fragment.blp") .. suffix',
        'prefix .. ("fragment.blp")',
        '((("fragment.blp"))) .. suffix',
        'prefix .. ((("fragment.blp")))',
        '(("fragment.blp") .. suffix)',
        '(("fragment.blp")) -- complete source comment\n .. suffix',
        '(("fragment.blp") .. ("tail.blp"))',
        'Wrap((("fragment.blp")) .. suffix)',
    ],
)
def test_public_probe_never_reads_parenthesized_or_nested_lua_concat_fragments(
    monkeypatch: pytest.MonkeyPatch, expression: str
) -> None:
    reader = _Reader({"fragment.blp": b"wrong", "tail.blp": b"wrong"})
    report = _probe(
        monkeypatch, reader, _map("Preload(" + expression + ")", source="war3map.lua")
    )
    assert report.items and {item.state for item in report.items} == {"unknown"}
    assert all("拼接" in " ".join(item.diagnostics) for item in report.items)
    assert not reader.reads and not report.confirmed_paths
    assert all(item.raw.startswith('"') for item in report.items)


@pytest.mark.parametrize(
    "expression", ['("fragment.blp") + suffix', 'prefix + ((("fragment.blp")))']
)
def test_public_probe_never_reads_parenthesized_jass_concat_fragments(
    monkeypatch: pytest.MonkeyPatch, expression: str
) -> None:
    reader = _Reader({"fragment.blp": b"wrong"})
    report = _probe(monkeypatch, reader, _map("call Preload(" + expression + ")"))
    assert report.items[0].state == "unknown" and not reader.reads


def test_concat_of_call_result_does_not_change_the_complete_literal_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader({"complete.blp": b"actual"})
    report = _probe(
        monkeypatch,
        reader,
        _map('Preload((("complete.blp"))) .. suffix', source="war3map.lua"),
    )
    assert report.confirmed_paths == ("complete.blp",) and reader.reads == {
        "complete.blp": 1
    }


@pytest.mark.parametrize(
    "encoded,actual",
    [
        (r"bad\n.blp", None),
        (r"f\x6fo.blp", "foo.blp"),
        (r"f\111o.blp", "foo.blp"),
        (r"bad\z   name.blp", "badname.blp"),
        (r"\xC3\xA9.blp", None),
        (r"bad\q.blp", None),
    ],
)
def test_public_lua_probe_never_uses_encoded_escape_spelling_as_path(
    monkeypatch: pytest.MonkeyPatch, encoded: str, actual: str | None
) -> None:
    files: dict[str, bytes | Exception] = {encoded: b"wrong archive member"}
    if actual is not None:
        files[actual] = b"correct runtime spelling"
    reader = _Reader(files)
    raw = '"' + encoded + '"'
    report = _probe(
        monkeypatch, reader, _map("Preload(" + raw + ")", source="war3map.lua")
    )
    assert report.items and report.items[0].raw == raw
    assert encoded not in reader.reads
    if reader.reads:
        assert actual is not None and set(reader.reads) == {actual}
        assert report.confirmed_paths == (actual,)
    else:
        assert not report.confirmed_paths and report.items[0].state in {
            "unknown",
            "unsafe",
        }
        assert report.items[0].diagnostics


@pytest.mark.parametrize("path", [r"Textures\new.blp", r"folder\x6fo.blp"])
def test_jass_single_backslash_path_conventions_are_preserved(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    reader = _Reader({path: b"JASS path evidence"})
    report = _probe(monkeypatch, reader, _map('call Preload("' + path + '")'))
    assert report.confirmed_paths == (path,) and reader.reads == {path: 1}


def test_lua_control_escape_keeps_exact_result_bytes_without_a_path_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader({r"bad\n.blp": b"wrong spelling"})
    report = _probe(
        monkeypatch, reader, _map(r'Preload("bad\n.blp")', source="war3map.lua")
    )
    item = report.items[0]
    assert item.state == "unsafe" and item.value == "bad\n.blp"
    assert item.literal_bytes == b"bad\n.blp" and item.literal_complete is True
    assert item.literal_source_encoding == "" and not reader.reads


def test_lua_byte_escape_unknown_source_encoding_preserves_bytes_and_tsv_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader(
        {r"\xC3\xA9.blp": b"wrong spelling", "é.blp": b"unproved encoding"}
    )
    raw = r'"\xC3\xA9.blp"'
    report = _probe(
        monkeypatch, reader, _map("Preload(" + raw + ")", source="war3map.lua")
    )
    item = report.items[0]
    assert item.state == "unknown" and item.raw == raw
    assert item.literal_bytes == b"\xc3\xa9.blp" and item.literal_complete is False
    assert item.literal_source_encoding == "" and item.diagnostics and not reader.reads
    rows = list(
        csv.reader(
            StringIO(candidates.format_resource_candidate_report_tsv(report)),
            delimiter="\t",
        )
    )
    assert all(len(row) == len(rows[0]) for row in rows)
    assert rows[1][rows[0].index("字面量结果字节HEX")] == b"\xc3\xa9.blp".hex()
    assert rows[1][rows[0].index("字面量源编码")] == ""


@pytest.mark.parametrize("encoded", [r"f\x6fo.blp", r"f\111o.blp"])
def test_ascii_lua_byte_escapes_confirm_only_the_complete_decoded_path(
    monkeypatch: pytest.MonkeyPatch, encoded: str
) -> None:
    reader = _Reader({encoded: b"wrong spelling", "foo.blp": b"correct"})
    report = _probe(
        monkeypatch, reader, _map('Preload("' + encoded + '")', source="war3map.lua")
    )
    item = report.items[0]
    assert report.confirmed_paths == ("foo.blp",) and reader.reads == {"foo.blp": 1}
    assert item.literal_bytes == b"foo.blp" and item.literal_complete is True
    assert item.literal_source_encoding == ""


def test_script_reference_mirror_never_marks_listed_fragments_or_escape_spellings_referenced() -> (
    None
):
    md = _map(
        r'Preload(("fragment.blp") .. suffix)'
        + "\n"
        + r'Preload("bad\n.blp")'
        + "\n"
        + r'Preload("f\x6fo.blp")',
        source="war3map.lua",
    )
    md.all_files = ["fragment.blp", r"bad\n.blp", r"f\x6fo.blp", "foo.blp"]
    report = build_resource_report(md)
    assert set(report.by_path) == {"foo.blp"}
    assert set(report.unreferenced_assets) == {
        "fragment.blp",
        r"bad\n.blp",
        r"f\x6fo.blp",
    }


def test_unknown_source_language_preserves_unconfirmed_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader({"ambiguous.blp": b"payload"})
    report = _probe(
        monkeypatch, reader, _map('Preload("ambiguous.blp")', source="custom.txt")
    )
    assert report.items[0].language == "unknown" and report.items[0].state == "unknown"
    assert not reader.reads


def test_slk_full_k_cells_recover_unicode_semicolons_and_recursive_toc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texture = "素材\\中文;完整.blp"
    slk = (
        'ID;PWXL;N;E\r\nC;X1;Y2;K"UI\\Frame;special.toc"\r\n'
        'C;X2;Y2;K"' + texture.replace(";", ";;") + '"\r\nE\r\n'
    ).encode("utf-8")
    toc = b'// "comment.blp"\n"UI\\Nested.fdf"\n'
    fdf = b'Texture "second.blp",\n'
    md = _map()
    md.all_files = ["Objects.slk"]
    reader = _Reader(
        {
            "Objects.slk": slk,
            "UI\\Frame;special.toc": toc,
            texture: b"BLP1",
            "UI\\Nested.fdf": fdf,
            "second.blp": b"BLP2",
        }
    )
    report = _probe(monkeypatch, reader, md)
    assert set(report.confirmed_paths) == {
        "UI\\Frame;special.toc",
        texture,
        "UI\\Nested.fdf",
        "second.blp",
    }
    assert len(report.items) == 4 and "comment.blp" not in reader.reads
    cell = next(item for item in report.items if item.path == texture)
    assert cell.binding == "SLK K cell" and ";;" in cell.raw
    assert cell.source_fingerprint == "bytes-sha256:" + hashlib.sha256(slk).hexdigest()
    refs = build_resource_content_references(md)
    assert (
        len(refs.items) == 4
        and refs.candidates.confirmed_paths == report.confirmed_paths
    )


@pytest.mark.parametrize(
    "path",
    ["..\\escape.blp", "C:\\outside.blp", "\\absolute.blp", "folder\\nul\x00.blp"],
)
def test_unsafe_candidates_keep_original_raw_evidence_without_reads(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    reader = _Reader({path: b"unsafe"})
    report = _probe(monkeypatch, reader, _map("call Preload(" + _quoted(path) + ")"))
    assert report.items[0].state == "unsafe" and report.items[0].value == path
    assert not reader.reads and not report.confirmed_paths


def test_failures_do_not_erase_later_confirmed_candidates_or_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _map(
        'call Preload("missing.blp")\ncall Preload("unreadable.blp")\ncall Preload("ok.blp")\ncall Preload("conflict.blp")'
    )
    md.all_files = ["unreadable.slk"]
    reader = _Reader(
        {
            "unreadable.blp": OSError("encoded read failed"),
            "ok.blp": b"BLP1",
            "conflict.blp": ResourcePathConflict("full A.blp | a.blp"),
            "unreadable.slk": OSError("full source error"),
        }
    )
    report = _probe(monkeypatch, reader, md)
    assert [item.state for item in report.items] == [
        "missing",
        "unreadable",
        "confirmed",
        "conflict",
    ]
    assert report.confirmed_paths == ("ok.blp",)
    assert report.diagnostics[0].source == "unreadable.slk"
    assert "full source error" in report.diagnostics[0].detail
    text = candidates.format_resource_candidate_report_tsv(report)
    assert (
        "full A.blp | a.blp" in text
        and "encoded read failed" in text
        and "full source error" in text
    )


def test_unavailable_archive_retains_candidates_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_md):
        raise OSError("archive identity cannot be reopened")

    monkeypatch.setattr(candidates, "open_map_source", unavailable)
    report = candidates.build_resource_candidate_report(
        _map('call Preload("still-visible.blp")')
    )
    assert (
        report.items[0].state == "unavailable"
        and report.items[0].raw == '"still-visible.blp"'
    )
    assert "identity" in report.diagnostics[0].detail


def test_changed_archive_downgrades_confirmed_paths_without_losing_read_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Changed(_Reader):
        def verify_source(self) -> None:
            super().verify_source()
            if self.verifications > 1:
                raise OSError("source replaced during candidate scan")

    reader = Changed({"read.blp": b"original bytes"})
    report = _probe(monkeypatch, reader, _map('call Preload("read.blp")'))
    assert report.items[0].state == "unstable" and report.items[0].size == 14
    assert report.items[0].sha256 == hashlib.sha256(b"original bytes").hexdigest()
    assert (
        not report.confirmed_paths and "source replaced" in report.diagnostics[0].detail
    )


def test_loaded_script_mutation_is_a_source_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _map('call Preload("read.blp")')

    class Changed(_Reader):
        def read_file(self, name: str) -> bytes:
            md.scripts["war3map.j"] += "\n// changed"
            return super().read_file(name)

    report = _probe(monkeypatch, Changed({"read.blp": b"x"}), md)
    assert not report.confirmed_paths and report.items[0].state == "unstable"
    assert "snapshot changed" in report.diagnostics[0].detail


def test_directory_reads_detect_aliases_and_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "Actual.blp"
    file.write_bytes(b"original")
    source = ResourceDirectorySource(str(tmp_path))
    before = file.stat()
    assert source.read_file("actual.blp") == b"original"
    source.verify_source()
    assert (
        file.read_bytes() == b"original"
        and file.stat().st_mtime_ns == before.st_mtime_ns
    )
    file.write_bytes(b"changed!")
    with pytest.raises(OSError, match="changed"):
        source.verify_source()
    other = tmp_path / "other.blp"
    other.write_bytes(b"conflict")
    source = ResourceDirectorySource(str(tmp_path))
    monkeypatch.setattr(source, "_entries", {"actual.blp": (file, other)})
    with pytest.raises(ResourcePathConflict, match="Actual.blp.*other.blp"):
        source.read_file("actual.blp")


@pytest.mark.parametrize("delivery", ["verify", "reread"])
def test_same_size_rewrites_are_detected_when_metadata_observations_are_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delivery: str
) -> None:
    file = tmp_path / "Actual.blp"
    original, changed = b"original", b"changed!"
    assert len(original) == len(changed)
    file.write_bytes(original)
    real_identity = directory_sources._identity
    initial_named = real_identity(file)
    with file.open("rb") as handle:
        initial_opened = directory_sources._descriptor_identity(handle)

    def frozen_identity(path: Path):
        return initial_named if path == file else real_identity(path)

    # Hosted Windows filesystems may postpone same-size write timestamps.
    # Freeze observability exactly, while all payload reads remain real I/O.
    monkeypatch.setattr(directory_sources, "_identity", frozen_identity)
    monkeypatch.setattr(
        directory_sources, "_descriptor_identity", lambda _handle: initial_opened
    )
    source = ResourceDirectorySource(str(tmp_path))
    assert source.read_file("actual.blp") == original
    source.verify_source()
    file.write_bytes(changed)
    assert (
        file.read_bytes() == changed
        and directory_sources._identity(file) == initial_named
    )
    with file.open("rb") as handle:
        assert directory_sources._descriptor_identity(handle) == initial_opened

    with pytest.raises(OSError, match="changed"):
        if delivery == "verify":
            source.verify_source()
        else:
            source.read_file("actual.blp")
    # A failed second read must not replace the first successful snapshot.
    with pytest.raises(OSError, match="changed"):
        source.verify_source()


def test_directory_nested_discovery_is_read_only(tmp_path: Path) -> None:
    (tmp_path / "table.slk").write_text(
        'ID;PWXL;N;E\nC;X1;Y1;K"模型.blp"\nE\n', encoding="utf-8"
    )
    asset = tmp_path / "模型.blp"
    asset.write_bytes(b"BLP1data")
    before = {
        entry.name: (entry.read_bytes(), entry.stat().st_mtime_ns)
        for entry in tmp_path.iterdir()
    }
    md = MapData(str(tmp_path), "directory", all_files=["table.slk"])
    report = candidates.build_resource_candidate_report(md)
    assert report.confirmed_paths == ("模型.blp",)
    assert before == {
        entry.name: (entry.read_bytes(), entry.stat().st_mtime_ns)
        for entry in tmp_path.iterdir()
    }


def test_full_coverage_and_reversible_raw_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 1500
    path = "=literal'\u2060-path.blp"
    script = "\n".join("call Preload(" + _quoted(path) + ")" for _ in range(count))
    reader = _Reader({path: b"BLP1"})
    report = _probe(monkeypatch, reader, _map(script))
    assert len(report.items) == count and reader.reads[path] == 1
    rows = list(
        csv.reader(
            StringIO(candidates.format_resource_candidate_report_tsv(report)),
            delimiter="\t",
        )
    )
    assert (
        len(rows) == count + 2
    )  # header plus explicit unknown-block coverage boundary
    assert decode_tsv_cell(rows[1][10]) == path
    assert find_resource_paths("目录\\" + "长" * 900 + ".blp") == (
        "目录\\" + "长" * 900 + ".blp",
    )


def test_duplicate_candidates_hash_the_read_payload_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"BLP1" * 1000
    original = candidates._digest
    hashes: Counter[bytes] = Counter()

    def observed(value: bytes) -> str:
        hashes[value] += 1
        return original(value)

    monkeypatch.setattr(candidates, "_digest", observed)
    reader = _Reader({"same.blp": payload})
    report = _probe(
        monkeypatch,
        reader,
        _map("\n".join('call Preload("same.blp")' for _ in range(100))),
    )
    assert (
        len(report.items) == 100
        and hashes[payload] == 1
        and reader.reads["same.blp"] == 1
    )


def test_multiline_unknown_path_is_preserved_as_one_reversible_tsv_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = "folder\r\n\ufeffembedded.blp"
    raw = "[==[" + value + "]==]"
    report = _probe(
        monkeypatch, _Reader({}), _map("Preload(" + raw + ")", source="war3map.lua")
    )
    decoded = value.replace("\r\n", "\n")  # Lua long strings normalize source newlines.
    assert report.items[0].state == "unsafe" and report.items[0].value == decoded
    rows = list(
        csv.reader(
            StringIO(
                candidates.format_resource_candidate_report_tsv(report), newline=""
            ),
            delimiter="\t",
        )
    )
    assert (
        len(rows) == 3
        and decode_tsv_cell(rows[1][9]) == raw
        and decode_tsv_cell(rows[1][10]) == decoded
    )


def test_audit_reports_only_read_confirmed_implicit_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md = _map('call Preload("hidden.blp")\ncall Preload("missing.blp")')
    _probe(monkeypatch, _Reader({"hidden.blp": b"BLP1"}), md)
    report = build_audit_report(md)
    assert "hidden.blp" in report.by_code["resources.discovered"].detail
    assert "missing.blp" not in report.by_code["resources.discovered"].detail


def test_real_archive_abstraction_recovers_unlisted_long_unicode_name(
    tmp_path: Path,
) -> None:
    path = "素材\\" + "long" * 100 + "一.blp"
    payload = b"BLP1synthetic"
    archive_path = tmp_path / "synthetic.w3x"
    archive_path.write_bytes(build_archive_bytes(path.encode("gbk"), ((0, payload),)))
    before = archive_path.read_bytes(), archive_path.stat().st_mtime_ns
    with MPQArchive(str(archive_path)) as archive:
        assert archive.list_files() == []
        expected = archive.source_identity
    md = MapData(
        str(archive_path),
        "synthetic",
        scripts={"war3map.j": "call Preload(" + _quoted(path) + ")"},
    )
    md.archive_source = PathArchiveSource(str(archive_path), expected_identity=expected)
    report = candidates.build_resource_candidate_report(md)
    assert (
        report.confirmed_paths == (path,)
        and report.items[0].sha256 == hashlib.sha256(payload).hexdigest()
    )
    assert before == (archive_path.read_bytes(), archive_path.stat().st_mtime_ns)
    assert md.all_files == []


def test_retained_archive_identity_rejects_a_replacement_before_probe(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "synthetic.w3x"
    archive_path.write_bytes(build_archive_bytes(b"asset.blp", ((0, b"BLP1original"),)))
    with MPQArchive(str(archive_path)) as archive:
        expected = archive.source_identity
    md = MapData(
        str(archive_path),
        "synthetic",
        scripts={"war3map.j": 'call Preload("asset.blp")'},
    )
    md.archive_source = PathArchiveSource(str(archive_path), expected_identity=expected)
    archive_path.write_bytes(
        build_archive_bytes(b"asset.blp", ((0, b"BLP1replacement"),))
    )
    report = candidates.build_resource_candidate_report(md)
    assert not report.confirmed_paths and report.items[0].state == "unavailable"
    assert report.diagnostics and "identity" in report.diagnostics[0].detail
