"""Author-supplied plaintext bundle validation and map loading."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from w3xtool.api import load_map
from w3xtool.load_context import MapLoadContext


def _write_bundle(root: Path, source: Path, files: dict[str, bytes]) -> None:
    payload_root = root / "files"
    payload_root.mkdir(parents=True)
    lines = [
        "W3XRAY-AUTHOR-BUNDLE\t1",
        f"source_sha256\t{hashlib.sha256(source.read_bytes()).hexdigest()}",
    ]
    for name, payload in files.items():
        path = payload_root.joinpath(*name.replace("\\", "/").split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        lines.append(f"file\t{name}\t{hashlib.sha256(payload).hexdigest()}")
    (root / "w3xray-author-bundle.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_valid_bundle_loads_script_when_source_archive_is_unreadable(tmp_path: Path) -> None:
    # Given: a protected source that is not a readable MPQ and an author-bound plaintext script.
    source = tmp_path / "protected.w3x"
    source.write_bytes(b"protected-container")
    bundle_root = tmp_path / "bundle"
    _write_bundle(
        bundle_root,
        source,
        {"war3map.j": b"function main takes nothing returns nothing\nendfunction\n"},
    )

    # When: map loading receives the verified author bundle.
    context = MapLoadContext(author_bundle_path=str(bundle_root))
    loaded = load_map(str(source), load_context=context)

    # Then: normal static script analysis continues from the author plaintext.
    assert "function main" in loaded.scripts["war3map.j"]
    assert "war3map.j" in loaded.all_files
    assert loaded.author_bundle_files == ("war3map.j",)


def test_bundle_can_supply_real_slk_object_data_without_executing_map_code(tmp_path: Path) -> None:
    # Given: an unreadable container and a verified real legacy AbilityData SLK payload.
    source = tmp_path / "protected.w3x"
    source.write_bytes(b"protected-container")
    slk = Path(__file__).parent / "fixtures" / "reference" / "AbilityDataSmall.slk"
    bundle_root = tmp_path / "bundle"
    _write_bundle(bundle_root, source, {"Units/AbilityData.slk": slk.read_bytes()})

    # When: only the author-supplied static object table is loaded.
    loaded = load_map(
        str(source),
        load_context=MapLoadContext(author_bundle_path=str(bundle_root)),
    )

    # Then: object fields and references are recovered without a loader or runtime dump.
    assert loaded.obj_index["AHwe"].name == "召唤水元素"
    assert len(loaded.obj_index["AHwe"].fields) > 10
    targets = {
        code
        for _label, resolved in loaded.references["AHwe"]
        for code, _name in resolved
    }
    assert "hwat" in targets


def test_bundle_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    # Given: a valid manifest whose source map changes after author publication.
    source = tmp_path / "protected.w3x"
    source.write_bytes(b"original")
    bundle_root = tmp_path / "bundle"
    _write_bundle(bundle_root, source, {"war3map.j": b"script"})
    source.write_bytes(b"different")
    bundle_module = importlib.import_module("w3xtool.author_plaintext_bundle")

    # When/Then: the bundle cannot be applied to a different map.
    with pytest.raises(bundle_module.AuthorBundleError, match="source SHA256"):
        bundle_module.load_author_plaintext_bundle(bundle_root, source)


def test_bundle_rejects_unsafe_internal_path(tmp_path: Path) -> None:
    # Given: a manifest attempts to map plaintext outside its bundle root.
    source = tmp_path / "protected.w3x"
    source.write_bytes(b"source")
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    (bundle_root / "w3xray-author-bundle.tsv").write_text(
        "\n".join((
            "W3XRAY-AUTHOR-BUNDLE\t1",
            f"source_sha256\t{source_hash}",
            f"file\t../evil.j\t{hashlib.sha256(b'evil').hexdigest()}",
        )) + "\n",
        encoding="utf-8",
    )
    bundle_module = importlib.import_module("w3xtool.author_plaintext_bundle")

    # When/Then: traversal is rejected before any file read.
    with pytest.raises(bundle_module.AuthorBundleError, match="unsafe internal path"):
        bundle_module.load_author_plaintext_bundle(bundle_root, source)


def test_bundle_rejects_symlinked_payload_root(tmp_path: Path) -> None:
    # Given: files/ redirects outside the author bundle.
    source = tmp_path / "protected.w3x"
    source.write_bytes(b"source")
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = b"trusted-script"
    (outside / "war3map.j").write_bytes(payload)
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    try:
        (bundle_root / "files").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    (bundle_root / "w3xray-author-bundle.tsv").write_text(
        "\n".join((
            "W3XRAY-AUTHOR-BUNDLE\t1",
            f"source_sha256\t{source_hash}",
            f"file\twar3map.j\t{hashlib.sha256(payload).hexdigest()}",
        )) + "\n",
        encoding="utf-8",
    )
    bundle_module = importlib.import_module("w3xtool.author_plaintext_bundle")

    # When/Then: a redirected trust root is rejected before hashing payloads.
    with pytest.raises(bundle_module.AuthorBundleError, match="symlink"):
        bundle_module.load_author_plaintext_bundle(bundle_root, source)


def test_bundle_rejects_payload_replaced_by_symlink_after_validation(tmp_path: Path) -> None:
    # Given: a valid payload is replaced with a same-content external symlink.
    source = tmp_path / "protected.w3x"
    source.write_bytes(b"source")
    bundle_root = tmp_path / "bundle"
    payload = b"trusted-script"
    _write_bundle(bundle_root, source, {"war3map.j": payload})
    bundle_module = importlib.import_module("w3xtool.author_plaintext_bundle")
    bundle = bundle_module.load_author_plaintext_bundle(bundle_root, source)
    external = tmp_path / "external.j"
    external.write_bytes(payload)
    bundled = bundle_root / "files" / "war3map.j"
    bundled.unlink()
    try:
        bundled.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    # When/Then: identity and no-follow checks reject the replacement despite its hash.
    with pytest.raises(bundle_module.AuthorBundleError, match="changed|symlink"):
        bundle.read_file("war3map.j")
