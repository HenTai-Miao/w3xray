"""Resource discovery shares SLK dialect decoding and cached-formula boundaries."""

from __future__ import annotations

import pytest

from gametool.resource_candidates import data_resource_candidates
from tests.test_resource_candidates import _Reader, _map, _probe


@pytest.mark.parametrize(
    ("producer", "encoded", "expected"),
    [
        ("PCALCOOO32", 'icons\\a""b.blp', 'icons\\a""b.blp'),
        ("PCALCOOO32", "icons\\a;;b.blp", "icons\\a;b.blp"),
        ("PSCALC3", 'icons\\a""b.blp', 'icons\\a"b.blp'),
        ("PSCALC3", "icons\\a;;b.blp", "icons\\a;;b.blp"),
    ],
)
def test_slk_resource_path_decodes_the_declared_producer_dialect(
    producer: str, encoded: str, expected: str
) -> None:
    raw = f'ID;{producer}\r\nC;X2;Y2;K"{encoded}"\r\nE\r\n'
    (item,) = data_resource_candidates("ObjectData.slk", raw.encode())
    assert item.path == expected
    assert item.raw == f'K"{encoded}"'
    assert raw[item.offset : item.end_offset] == item.raw
    assert item.line == 2


def test_slk_cached_formula_path_remains_unknown_and_is_never_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b'ID;PCALCOOO32\nC;X2;Y2;K"cached.blp";Eformula\nE\n'
    md = _map()
    md.all_files = ["ObjectData.slk"]
    reader = _Reader({"ObjectData.slk": raw, "cached.blp": b"unrelated payload"})
    report = _probe(monkeypatch, reader, md)
    (item,) = report.items
    assert item.path == "cached.blp" and item.state == "unknown"
    assert item.raw == 'K"cached.blp"'
    assert any("Eformula" in note for note in item.diagnostics)
    assert not report.confirmed_paths
    assert reader.reads == {"ObjectData.slk": 1}
