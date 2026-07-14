"""Safe original and PNG icon publication tests."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from w3xtool.batch_icon_export import (
    IconExportState,
    export_anonymous_icon,
    export_named_icon,
)
from w3xtool.extraction_ledger import BlockSource, BlockState
from w3xtool.icon_resources import AnonymousIconResource, NamedIconResource


def _anonymous_resource(payload: bytes, *, block_index: int = 9) -> AnonymousIconResource:
    digest = hashlib.sha256(payload).hexdigest()
    return AnonymousIconResource(
        block_index=block_index,
        payload=payload,
        sha256=digest,
        basename=f"block_{block_index:06d}_{digest[:8]}",
        source_path="map.w3x",
        ledger_source=BlockSource.ARCHIVE_RECOVERED,
        ledger_state=BlockState.DECODED,
    )


def _named_resource(path: str, payload: bytes) -> NamedIconResource:
    return NamedIconResource(
        requested_path=path,
        normalized_path=path.replace("/", "\\"),
        resolved_path=path.replace("/", "\\"),
        source_path="map.w3x",
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        objects=(),
    )


def _one_pixel_blp() -> bytes:
    buffer = bytearray(20 + 128 + 1024)
    buffer[0:4] = b"BLP2"
    struct.pack_into("<I", buffer, 4, 1)
    struct.pack_into("<BBBB", buffer, 8, 1, 0, 0, 0)
    struct.pack_into("<II", buffer, 12, 1, 1)
    struct.pack_into("<I", buffer, 20, len(buffer))
    struct.pack_into("<I", buffer, 84, 1)
    buffer[148:152] = bytes((10, 20, 30, 255))
    buffer.append(0)
    return bytes(buffer)


def test_export_keeps_original_when_png_decode_fails(tmp_path: Path) -> None:
    # Given
    resource = _anonymous_resource(b"BLP1broken")

    # When
    record = export_anonymous_icon(str(tmp_path), resource)

    # Then
    original = tmp_path / "图标/原始/匿名" / f"{resource.basename}.blp"
    assert original.read_bytes() == b"BLP1broken"
    assert record.original_written is True
    assert record.png_written is False
    assert record.state is IconExportState.PNG_FAILED


def test_named_export_writes_original_and_viewable_png(tmp_path: Path) -> None:
    # Given
    resource = _named_resource("Icons/BTNHero.blp", _one_pixel_blp())

    # When
    record = export_named_icon(str(tmp_path), resource)

    # Then
    assert (tmp_path / "图标/原始/具名/Icons/BTNHero.blp").read_bytes() == resource.payload
    assert (tmp_path / "图标/PNG/具名/Icons/BTNHero.png").read_bytes().startswith(b"\x89PNG")
    assert record.state is IconExportState.COMPLETE
    assert record.original_written and record.png_written


def test_named_export_cannot_escape_the_output_root(tmp_path: Path) -> None:
    # Given
    resource = _named_resource("../../outside.blp", b"BLP1broken")

    # When
    record = export_named_icon(str(tmp_path), resource)

    # Then
    assert record.state is IconExportState.UNSAFE_PATH
    assert not (tmp_path.parent / "outside.blp").exists()


def test_named_export_rejects_unc_paths_instead_of_normalizing_them(tmp_path: Path) -> None:
    # Given
    resource = _named_resource(r"\\server\share\outside.blp", b"BLP1broken")

    # When
    record = export_named_icon(str(tmp_path), resource)

    # Then
    assert record.state is IconExportState.UNSAFE_PATH
    assert not (tmp_path / "server/share/outside.blp").exists()


def test_named_export_hash_suffixes_a_different_existing_payload(tmp_path: Path) -> None:
    # Given
    first = _named_resource("Icons/BTN.blp", b"BLP1first")
    second = _named_resource("Icons/BTN.blp", b"BLP1second")
    _ = export_named_icon(str(tmp_path), first)

    # When
    record = export_named_icon(str(tmp_path), second)

    # Then
    expected = tmp_path / "图标/原始/具名/Icons" / f"BTN_{second.sha256[:8]}.blp"
    assert expected.read_bytes() == second.payload
    assert record.original_relative_path.endswith(f"BTN_{second.sha256[:8]}.blp")


def test_repeating_the_same_export_reuses_both_stable_paths(tmp_path: Path) -> None:
    # Given
    resource = _named_resource("Icons/BTNHero.blp", _one_pixel_blp())
    first = export_named_icon(str(tmp_path), resource)

    # When
    second = export_named_icon(str(tmp_path), resource)

    # Then
    assert second.original_relative_path == first.original_relative_path
    assert second.png_relative_path == first.png_relative_path
