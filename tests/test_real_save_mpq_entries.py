"""Save archives read exact locale/platform entries instead of a default member."""

from __future__ import annotations

from pathlib import Path

from gametool.real_save_files import analyze_real_save_path

from .test_archive_export_recovery import _archive_bytes


def test_save_mpq_retains_every_locale_platform_and_duplicate_hash_entry(
    tmp_path: Path,
):
    members = [
        ("war3map.j", 0, 0, b'call Preload("-load neutral-code")', True),
        ("war3map.j", 0x409, 0, b'call Preload("-load locale-code")', True),
        ("war3map.j", 0, 1, b'call Preload("-load platform-code")', True),
        ("war3map.j", 0, 0, b'call Preload("-load duplicate-code")', True),
    ]
    payload = _archive_bytes(members, duplicate_hash_entry=True)
    source = tmp_path / "save.mpq"
    source.write_bytes(payload)
    before = source.stat()
    report = analyze_real_save_path(source)
    assert report.complete
    children = report.files[0].members
    assert len(children) == 5
    identities = [child.archive_member for child in children]
    assert all(identity is not None for identity in identities)
    assert len({identity["hash_index"] for identity in identities if identity}) == 5
    by_block = {}
    for child in children:
        assert child.archive_member is not None
        identity = child.archive_member
        by_block.setdefault(identity["block_index"], []).append(child)
        block_index = identity["block_index"]
        assert isinstance(block_index, int)
        expected = members[block_index]
        assert identity["name"] == expected[0]
        assert (identity["locale"], identity["platform"]) == expected[1:3]
        assert child.raw_text == expected[3].decode("utf-8")
        assert child.to_dict()["archive_member"] == identity
    assert {block: len(records) for block, records in by_block.items()} == {
        0: 1,
        1: 1,
        2: 1,
        3: 2,
    }
    assert source.read_bytes() == payload
    after = source.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )


def test_nested_save_archive_keeps_each_parent_and_child_entry_identity(tmp_path: Path):
    # The member is explicitly named by the archive listfile; its non-default
    # language must still be inspected under the selected physical parent.
    inner = _archive_bytes(
        [
            ("(listfile)", 0, 0, b"war3map.j\n", False),
            ("war3map.j", 0x409, 0, b'call Preload("-load nested-code")', False),
        ]
    )
    payload = _archive_bytes(
        [
            ("(listfile)", 0, 0, b"nested.mpq\n", False),
            ("nested.mpq", 0x409, 0, inner, False),
        ]
    )
    source = tmp_path / "outer.mpq"
    source.write_bytes(payload)
    report = analyze_real_save_path(source)
    assert report.complete
    nested = next(member for member in report.files[0].members if member.kind == "mpq")
    assert nested.archive_member is not None
    assert nested.archive_member["name"] == "nested.mpq"
    assert nested.archive_member["locale"] == 0x409
    script = next(member for member in nested.members if member.codes)
    assert script.archive_member is not None
    assert script.archive_member["locale"] == 0x409
    assert script.codes[0].code == "-load nested-code"
    flattened = report.files[0].to_dict()["members"]
    assert isinstance(flattened, list)
    nested_index = next(
        row["member_index"] for row in flattened if row["kind"] == "mpq"
    )
    leaf = next(row for row in flattened if row["codes"])
    assert leaf["parent_member_index"] == nested_index


def test_nondefault_listfile_discovers_its_own_named_members(tmp_path: Path):
    payload = _archive_bytes(
        [
            ("(listfile)", 0x409, 0, b"localized.txt\n", True),
            ("localized.txt", 0x409, 0, b"-load localized-only-code", True),
        ]
    )
    source = tmp_path / "localized.mpq"
    source.write_bytes(payload)
    report = analyze_real_save_path(source)
    assert report.complete
    children = report.files[0].members
    assert len(children) == 2
    text = next(member for member in children if member.codes)
    assert text.raw_text == "-load localized-only-code"
    assert text.archive_member is not None
    assert text.archive_member["name"] == "localized.txt"
    assert text.archive_member["locale"] == 0x409
