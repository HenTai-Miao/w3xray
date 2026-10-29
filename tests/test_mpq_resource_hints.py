"""Pinned inert name hints recover only independently verified MPQ entries."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import struct

import pytest

from gametool import build_mpq_resource_hints as builder
from gametool import mpq_resource_hints as catalog
from gametool.api import export_all_files
from gametool.mpq_crypto import _decrypt, hash_name_bytes

from .test_archive_export_recovery import _archive_bytes
from .test_mpq_names_locale import _encrypt


def _literal_source(names: tuple[str, ...]) -> bytes:
    return (
        "STANDARD_RESOURCE_NAMES = tuple("
        + json.dumps("\n".join(names))
        + ".strip().splitlines())\n"
    ).encode()


def _document(count: int) -> bytes:
    return (
        f"`war3_mpq_names.py` 内含 {count} 条固定路径\n"
        "| 来源 | SHA256 |\n"
        f"| `Terrain.slk` | `{'1' * 64}` |\n"
        f"| CASC 文件路径清单 | `{'2' * 64}` |\n"
    ).encode()


def _pin(monkeypatch: pytest.MonkeyPatch, source: bytes, document: bytes) -> None:
    monkeypatch.setattr(
        builder, "SOURCE_FILE_SHA256", hashlib.sha256(source).hexdigest()
    )
    monkeypatch.setattr(
        builder, "SOURCE_DOCUMENT_SHA256", hashlib.sha256(document).hexdigest()
    )


def _records(output: Path) -> list[tuple[str, dict[str, str]]]:
    return [
        (
            cells[0],
            dict(cell.split("=", 1) for cell in cells[1:]),
        )
        for line in (output / "RecoveredNames" / "manifest.tsv")
        .read_text(encoding="utf-8")
        .splitlines()
        if (cells := line.split("\t"))
    ]


def _export(tmp_path: Path, data: bytes, *, names: tuple[str, ...] = ()) -> Path:
    source = tmp_path / "source.w3x"
    source.write_bytes(data)
    before = source.stat()
    output = tmp_path / "export"
    export_all_files(str(source), str(output), external_names=names)
    assert source.read_bytes() == data
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    return output


def test_catalog_preserves_every_pinned_source_name_and_provenance() -> None:
    assert len(catalog.RESOURCE_NAME_HINTS) == catalog.RESOURCE_NAME_COUNT == 1191
    assert (
        hashlib.sha256(
            ("\n".join(catalog.RESOURCE_NAME_HINTS) + "\n").encode()
        ).hexdigest()
        == (catalog.RESOURCE_NAMES_SHA256)
        == "c942485e2d8a8c1cc5d5c2c87cb6d5a92525728c513fdd0f090cc85844142303"
    )
    assert catalog.SOURCE_COMMIT == "39ddabe2dc16ca7c3be9911c41dc22c83d1b9c4d"
    assert catalog.SOURCE_FILE_SHA256 == (
        "adeaf732c55c11929dc8e5e59d69f4a699e89f80e529faf3a7e27a1357ab1ac9"
    )
    assert catalog.SOURCE_DOCUMENT_SHA256 == (
        "b323153c565e9af139552dfe74d8483b3323298687683c22b9c51184b1a968ec"
    )
    assert len(catalog.SOURCE_REFERENCE_SHA256) == 4
    assert r"ReplaceableTextures\CommandButtons\BTNNightElfBUild.blp" in (
        catalog.RESOURCE_NAME_HINTS
    )
    assert r"ReplaceableTextures\CommandButtons\BTNNightElfBuild.blp" in (
        catalog.RESOURCE_NAME_HINTS
    )


def test_automatic_export_recovers_entire_catalog_and_retains_unknown_blocks(
    tmp_path: Path,
) -> None:
    payloads = {
        index: b"BLP1" + struct.pack("<I", index)
        for index in range(catalog.RESOURCE_NAME_COUNT)
    }
    members = [
        (name, 0, 0, payloads[index], True)
        for index, name in enumerate(catalog.RESOURCE_NAME_HINTS)
    ]
    members.extend(
        (
            ("PrivateUnlistedEncrypted.bin", 0, 0, b"private-unknown-encrypted", True),
            ("PrivateUnlistedPlain.bin", 0, 0, b"private-unknown-plain", False),
        )
    )
    data = _archive_bytes(members)

    output = _export(tmp_path, data)

    confirmed = [row for status, row in _records(output) if status == "OK"]
    assert {int(row["block"]) for row in confirmed} == set(payloads)
    assert len(confirmed) == len(payloads)
    for row in confirmed:
        payload = (output / json.loads(row["path"])).read_bytes()
        assert payload == payloads[int(row["block"])]
        assert row["sha256"] == hashlib.sha256(payload).hexdigest()
        assert json.loads(row["hint_catalog"]) == catalog.CATALOG_ID
    unknown_index = catalog.RESOURCE_NAME_COUNT
    assert (output / "UnknownRaw" / f"File{unknown_index:06d}.mpqraw").read_bytes() == (
        _encrypt(
            b"private-unknown-encrypted",
            hash_name_bytes(b"PrivateUnlistedEncrypted.bin", 3),
        )
    )
    anonymous = tuple((output / "Unknown").iterdir())
    assert len(anonymous) == 1
    assert anonymous[0].stem == f"File{unknown_index + 1:06d}"
    assert anonymous[0].read_bytes() == b"private-unknown-plain"
    report = json.loads(
        (output / "RecoveredNames" / "name-hint-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["hint_count"] == 1191
    assert report["candidate_only"] is True
    assert report["game_version"] is None
    assert report["source_file_sha256"] == catalog.SOURCE_FILE_SHA256
    assert report["source_document_sha256"] == catalog.SOURCE_DOCUMENT_SHA256
    assert report["source_commit"] == catalog.SOURCE_COMMIT
    assert report["ordered_names_sha256"] == catalog.RESOURCE_NAMES_SHA256
    assert report["source_declared_inputs"] == [
        {"name": name, "sha256": digest}
        for name, digest in catalog.SOURCE_REFERENCE_SHA256
    ]


def test_implicit_resource_preserves_duplicate_blocks_locales_platforms_and_aliases(
    tmp_path: Path,
) -> None:
    entries = (
        (0, 0, b"BLP1first"),
        (0, 0, b"BLP1same-raw-name-other-block"),
        (0x0409, 0, b"BLP1locale0409"),
        (0, 1, b"BLP1platform01"),
    )
    name = r"ReplaceableTextures\CommandButtons\BTNNightElfBuild.blp"
    data = _archive_bytes(
        [
            (name, locale, platform, payload, True)
            for locale, platform, payload in entries
        ]
    )

    output = _export(tmp_path, data)

    records = _records(output)
    confirmed = [row for status, row in records if status == "OK"]
    assert {int(row["block"]) for row in confirmed} == set(range(len(entries)))
    for row in confirmed:
        locale, platform, payload = entries[int(row["block"])]
        assert (int(row["locale"]), int(row["platform"])) == (locale, platform)
        assert (output / json.loads(row["path"])).read_bytes() == payload
    assert len({row["path"] for row in confirmed}) == len(entries)
    assert {
        json.loads(row["name"]) for status, row in records if status in {"OK", "ALIAS"}
    } == {
        name,
        r"ReplaceableTextures\CommandButtons\BTNNightElfBUild.blp",
    }


def test_implicit_hint_outside_real_probe_chain_remains_unknown(tmp_path: Path) -> None:
    data = bytearray(_archive_bytes([("FullScreen.blp", 0, 0, b"BLP1hidden", True)]))
    key = hash_name_bytes(b"(hash table)", 3)
    rows = list(struct.iter_unpack("<IIHHI", _decrypt(bytes(data[32:160]), key)))
    slot = next(i for i, row in enumerate(rows) if row[4] == 0)
    rows[(slot + 1) % len(rows)] = rows[slot]
    rows[slot] = (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)
    data[32:160] = _encrypt(b"".join(struct.pack("<IIHHI", *row) for row in rows), key)

    output = _export(tmp_path, bytes(data))

    assert not (output / "FullScreen.blp").exists()
    assert (output / "UnknownRaw" / "File000000.mpqraw").is_file()
    records = _records(output)
    assert all(status != "OK" for status, _ in records)
    assert any(status == "FAIL" for status, _ in records)


def test_catalog_report_collision_preserves_actual_archive_member(
    tmp_path: Path,
) -> None:
    name = r"RecoveredNames\name-hint-catalog.json"
    payload = b'{"actual_member":true}'
    data = _archive_bytes(
        [
            (name, 0, 0, payload, True),
            ("FullScreen.blp", 0, 0, b"BLP1implicit", True),
        ]
    )

    output = _export(tmp_path, data, names=(name,))

    assert (output / name).read_bytes() == payload
    generated = json.loads(
        (output / "RecoveredNames" / "name-hint-catalog-2.json").read_text(
            encoding="utf-8"
        )
    )
    assert generated["catalog_id"] == catalog.CATALOG_ID
    assert (output / "FullScreen.blp").read_bytes() == b"BLP1implicit"


def test_implicit_encrypted_model_follows_verified_references_to_closure(
    tmp_path: Path,
) -> None:
    data = _archive_bytes(
        [
            (r"UI\BTNTest.mdx", 0, 0, b'MDLX\0"Private\\second.mdx"\0', True),
            (r"Private\second.mdx", 0, 0, b'MDLX\0"Private\\last.blp"\0', True),
            (r"Private\last.blp", 0, 0, b"BLP1end-of-chain", True),
        ]
    )

    output = _export(tmp_path, data)

    records = _records(output)
    assert {int(row["block"]) for status, row in records if status == "OK"} == {0, 1, 2}
    assert (output / "Private" / "last.blp").read_bytes() == b"BLP1end-of-chain"
    assert not (output / "UnknownRaw").exists()


def test_literal_parser_preserves_all_names_order_case_and_duplicate_lines() -> None:
    names = ("Same.blp", "same.blp", "Same.blp") + tuple(
        f"Resources\\name{index}.blp" for index in range(12001)
    )
    assert builder.extract_resource_names(_literal_source(names)) == names


@pytest.mark.parametrize(
    "expression",
    [
        "tuple(__import__('pathlib').Path({sentinel}).write_text('executed'))",
        "tuple(('Full' + 'Screen.blp').strip().splitlines())",
        "tuple(f'FullScreen.blp'.strip().splitlines())",
        "tuple('FullScreen.blp'.strip('x').splitlines())",
        "tuple('FullScreen.blp'.strip().splitlines(True))",
    ],
)
def test_literal_parser_rejects_dynamic_or_changed_semantics_without_execution(
    tmp_path: Path, expression: str
) -> None:
    sentinel = tmp_path / "executed"
    source = "STANDARD_RESOURCE_NAMES = " + expression.format(
        sentinel=repr(str(sentinel))
    )
    with pytest.raises(ValueError):
        builder.extract_resource_names(source.encode())
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "suffix",
    [
        "\nraise RuntimeError('must not execute')",
        "\nimport pathlib",
        "\nSTANDARD_RESOURCE_NAMES = ()",
    ],
)
def test_literal_parser_rejects_unreviewed_extra_statements(suffix: str) -> None:
    with pytest.raises(ValueError, match="exactly one literal assignment"):
        builder.extract_resource_names(
            _literal_source(("FullScreen.blp",)) + suffix.encode()
        )


@pytest.mark.parametrize(
    "name", [r"..\outside.blp", r"C:\outside.blp", r"\\host\x.blp"]
)
def test_literal_parser_rejects_unsafe_candidate_paths(name: str) -> None:
    with pytest.raises(ValueError, match="unsafe resource hint"):
        builder.extract_resource_names(_literal_source((name,)))


def test_generator_is_deterministic_complete_and_keeps_inputs_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ("FullScreen.blp", "Case.blp", "case.blp", "FullScreen.blp")
    source = _literal_source(names)
    document = _document(len(names))
    _pin(monkeypatch, source, document)
    root = tmp_path / "source"
    (root / "docs").mkdir(parents=True)
    source_path = root / builder.SOURCE_FILE
    document_path = root / builder.SOURCE_DOCUMENT
    source_path.write_bytes(source)
    document_path.write_bytes(document)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (source_path, document_path)
    }
    outputs = (tmp_path / "first.py", tmp_path / "second.py")

    for output in outputs:
        builder.generate_catalog(root, output)

    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    module = ast.parse(outputs[0].read_text(encoding="utf-8"))
    hints = next(
        node.value
        for node in module.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "RESOURCE_NAME_HINTS"
    )
    assert isinstance(hints, ast.Tuple)
    assert (
        tuple(node.value for node in hints.elts if isinstance(node, ast.Constant))
        == names
    )
    for path, evidence in before.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == evidence


@pytest.mark.parametrize("changed", ["source", "document", "count", "source-output"])
def test_generator_rejects_invalid_inputs_without_replacing_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    source = _literal_source(("FullScreen.blp",))
    document = _document(2 if changed == "count" else 1)
    _pin(monkeypatch, source, document)
    root = tmp_path / "source"
    (root / "docs").mkdir(parents=True)
    (root / builder.SOURCE_FILE).write_bytes(
        source + (b"\n" if changed == "source" else b"")
    )
    (root / builder.SOURCE_DOCUMENT).write_bytes(
        document + (b"\n" if changed == "document" else b"")
    )
    output = (root if changed == "source-output" else tmp_path) / "output.py"
    output.write_bytes(b"existing output evidence")

    with pytest.raises(ValueError):
        builder.generate_catalog(root, output)

    assert output.read_bytes() == b"existing output evidence"
