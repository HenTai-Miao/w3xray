"""Extraction ledger state aggregation and deterministic serialization."""

from __future__ import annotations

import json

import pytest

from w3xtool.extraction_ledger import (
    BlockSource,
    BlockState,
    ExtractionEntry,
    ExtractionLedgerError,
    ExtractionStatus,
    build_extraction_ledger,
)
from w3xtool.extraction_ledger_format import format_extraction_json, format_extraction_tsv


_SHA256 = "a" * 64


def _entry(
    state: BlockState,
    *,
    source: BlockSource = BlockSource.ARCHIVE_NAMED,
    block_index: int | None = 0,
    encrypted: bool = False,
    sha256: str = _SHA256,
) -> ExtractionEntry:
    return ExtractionEntry(
        block_index=block_index,
        internal_path="war3map.j",
        state=state,
        source=source,
        declared_size=6,
        written_size=6 if sha256 else 0,
        sha256=sha256,
        encrypted=encrypted,
        error_code="",
        detail="",
    )


def test_all_decoded_and_supplemented_entries_are_complete() -> None:
    # Given: every archive block has verified plaintext bytes.
    entries = (
        _entry(BlockState.DECODED),
        _entry(
            BlockState.SUPPLEMENTED,
            source=BlockSource.COMPAT_PLAINTEXT,
            block_index=None,
        ),
    )

    # When: the immutable ledger is built.
    ledger = build_extraction_ledger("map.w3x", "b" * 64, entries)

    # Then: the map is byte-complete.
    assert ledger.status is ExtractionStatus.COMPLETE


def test_only_unresolved_encrypted_entries_are_encrypted_blocked() -> None:
    # Given: all unresolved blocks are specifically encrypted.
    entries = (
        _entry(
            BlockState.ENCRYPTED_BLOCKED,
            source=BlockSource.RAW_PAYLOAD,
            encrypted=True,
            sha256="",
        ),
    )

    # When: the ledger aggregates its map status.
    ledger = build_extraction_ledger("map.w3x", "b" * 64, entries)

    # Then: it reports the precise encryption classification.
    assert ledger.status is ExtractionStatus.ENCRYPTED_BLOCKED


def test_raw_fallback_is_partial_even_with_encrypted_block() -> None:
    # Given: one general raw fallback and one encrypted-only obstruction.
    entries = (
        _entry(BlockState.RAW_ONLY, source=BlockSource.RAW_PAYLOAD),
        _entry(
            BlockState.ENCRYPTED_BLOCKED,
            source=BlockSource.RAW_PAYLOAD,
            encrypted=True,
            sha256="",
        ),
    )

    # When: the ledger aggregates its map status.
    ledger = build_extraction_ledger("map.w3x", "b" * 64, entries)

    # Then: incomplete non-encryption evidence makes the result partial.
    assert ledger.status is ExtractionStatus.PARTIAL


def test_damage_precedes_partial_and_encryption() -> None:
    # Given: damaged structure coexists with less severe incomplete entries.
    entries = (
        _entry(BlockState.RAW_ONLY, source=BlockSource.RAW_PAYLOAD),
        _entry(
            BlockState.DAMAGED,
            source=BlockSource.RAW_PAYLOAD,
            sha256="",
        ),
    )

    # When: the ledger aggregates its map status.
    ledger = build_extraction_ledger("map.w3x", "b" * 64, entries)

    # Then: damaged has the documented highest priority.
    assert ledger.status is ExtractionStatus.DAMAGED


def test_entry_rejects_verified_state_without_sha256() -> None:
    # Given/When/Then: a decoded entry cannot claim verification without a digest.
    with pytest.raises(ExtractionLedgerError, match="SHA-256"):
        _ = _entry(BlockState.DECODED, sha256="")


def test_json_and_tsv_share_stable_schema_and_sanitize_controls() -> None:
    # Given: a ledger contains an untrusted detail and entries in reverse block order.
    later = _entry(BlockState.DECODED, block_index=2)
    earlier = ExtractionEntry(
        block_index=1,
        internal_path="Unknown/block_000001.j",
        state=BlockState.DECODED,
        source=BlockSource.ARCHIVE_RECOVERED,
        declared_size=6,
        written_size=6,
        sha256=_SHA256,
        encrypted=False,
        error_code="",
        detail="line\n\x1b[2Jdetail",
    )
    ledger = build_extraction_ledger("map\n.w3x", "b" * 64, (later, earlier))

    # When: machine-readable and tabular views are rendered.
    json_text = format_extraction_json(ledger)
    tsv_text = format_extraction_tsv(ledger)
    payload = json.loads(json_text)

    # Then: ordering, schema, status, and inert single-line text agree.
    assert payload["schema_version"] == 1
    assert payload["status"] == "complete"
    assert [entry["block_index"] for entry in payload["entries"]] == [1, 2]
    assert "\x1b" not in json_text and "\x1b" not in tsv_text
    assert "line detail" in tsv_text
    assert tsv_text.splitlines()[0].startswith("block_index\tinternal_path\tstate")
