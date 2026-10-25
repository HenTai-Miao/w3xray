"""Join only physically adjacent captured ranges without filling missing bytes."""

from __future__ import annotations

from collections.abc import Iterable, Iterator


def contiguous_regions(
    regions: Iterable[tuple[int, bytes]],
) -> Iterator[tuple[int, bytes]]:
    start = end = 0
    chunks: list[bytes] = []
    for base, data in sorted((base, data) for base, data in regions if data):
        if chunks and base != end:
            yield start, chunks[0] if len(chunks) == 1 else b"".join(chunks)
            chunks = []
        if not chunks:
            start = base
        chunks.append(data)
        end = base + len(data)
    if chunks:
        yield start, chunks[0] if len(chunks) == 1 else b"".join(chunks)
