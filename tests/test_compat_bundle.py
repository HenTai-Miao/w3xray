"""Source-bound compatibility bundle parsing and file identity safety."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from w3xtool.compat_bundle import COMPAT_MANIFEST_NAME, CompatBundleError, load_compat_bundle


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_source(tmp_path: Path, payload: bytes = b"map-source") -> Path:
    source = tmp_path / "source.w3x"
    source.write_bytes(payload)
    return source


def _write_manifest(root: Path, source: Path, rows: tuple[str, ...]) -> None:
    root.mkdir()
    lines = (
        "W3XRAY-COMPAT-BUNDLE\t1",
        f"source_sha256\t{_sha(source.read_bytes())}",
        *rows,
    )
    (root / COMPAT_MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_bundle_accepts_bound_name_file_and_key(tmp_path: Path) -> None:
    # Given: every compatibility evidence row is bound to one source map.
    source = _write_source(tmp_path)
    root = tmp_path / "bundle"
    script = b"function main takes nothing returns nothing\nendfunction\n"
    _write_manifest(
        root,
        source,
        (
            "name\twar3map.wts",
            f"file\twar3map.j\t{_sha(script)}",
            f"mpq_key\t7\t89ABCDEF\t{_sha(b'plain')}\tUnknown/secret.bin",
        ),
    )
    payload = root / "files" / "war3map.j"
    payload.parent.mkdir()
    payload.write_bytes(script)

    # When: the compatibility directory crosses the trust boundary.
    bundle = load_compat_bundle(root, source)

    # Then: names, immutable plaintext evidence, and final MPQ keys are typed.
    assert bundle.source_sha256 == _sha(source.read_bytes())
    assert bundle.names == ("war3map.wts",)
    assert bundle.files[0].name == "war3map.j"
    assert bundle.files[0].read() == script
    assert bundle.keys[0].block_index == 7
    assert bundle.keys[0].key == 0x89ABCDEF
    assert bundle.keys[0].internal_path == "Unknown/secret.bin"


def test_bundle_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    # Given: a manifest was created for an earlier source identity.
    source = _write_source(tmp_path, b"before")
    root = tmp_path / "bundle"
    _write_manifest(root, source, ("name\twar3map.j",))
    source.write_bytes(b"after")

    # When/Then: the complete bundle is rejected before evidence is used.
    with pytest.raises(CompatBundleError, match="source SHA-256 mismatch"):
        _ = load_compat_bundle(root, source)


@pytest.mark.parametrize(
    "row",
    (
        "name\t../escape.j",
        "name\tC:\\absolute.j",
        "mpq_key\t-1\t00000000\t" + "a" * 64 + "\t-",
        "mpq_key\t0\tnot-a-key\t" + "a" * 64 + "\t-",
        "file\twar3map.j\tnot-a-hash",
    ),
)
def test_bundle_rejects_unsafe_or_malformed_rows(tmp_path: Path, row: str) -> None:
    # Given: one malformed or unsafe compatibility row.
    source = _write_source(tmp_path)
    root = tmp_path / "bundle"
    _write_manifest(root, source, (row,))

    # When/Then: strict parsing fails closed.
    with pytest.raises(CompatBundleError):
        _ = load_compat_bundle(root, source)


def test_bundle_rejects_casefolded_duplicate_paths(tmp_path: Path) -> None:
    # Given: two rows would address the same MPQ path on case-insensitive lookup.
    source = _write_source(tmp_path)
    root = tmp_path / "bundle"
    _write_manifest(root, source, ("name\tUI\\Main.fdf", "name\tui/main.fdf"))

    # When/Then: row order cannot decide which declaration wins.
    with pytest.raises(CompatBundleError, match="duplicate internal path"):
        _ = load_compat_bundle(root, source)


def test_bundle_rejects_payload_replaced_after_validation(tmp_path: Path) -> None:
    # Given: a verified regular plaintext file is replaced before its next read.
    source = _write_source(tmp_path)
    root = tmp_path / "bundle"
    body = b"trusted"
    _write_manifest(root, source, (f"file\twar3map.j\t{_sha(body)}",))
    payload = root / "files" / "war3map.j"
    payload.parent.mkdir()
    payload.write_bytes(body)
    bundle = load_compat_bundle(root, source)
    payload.write_bytes(b"changed")

    # When/Then: the retained identity fails closed even before digest use.
    with pytest.raises(CompatBundleError, match="changed after validation"):
        _ = bundle.files[0].read()


def test_bundle_rejects_symlinked_payload_root(tmp_path: Path) -> None:
    # Given: files/ redirects trust outside the compatibility directory.
    source = _write_source(tmp_path)
    root = tmp_path / "bundle"
    body = b"trusted"
    _write_manifest(root, source, (f"file\twar3map.j\t{_sha(body)}",))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "war3map.j").write_bytes(body)
    try:
        (root / "files").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    # When/Then: the redirected payload root is never traversed.
    with pytest.raises(CompatBundleError, match="symlink"):
        _ = load_compat_bundle(root, source)
