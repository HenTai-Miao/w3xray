"""Bounded writes into an already-open staged output descriptor."""

from __future__ import annotations

from collections.abc import Iterable
import errno
import os

from .durable_io import sync_file_descriptor


def write_chunks_to_descriptor(descriptor: int, chunks: Iterable[bytes]) -> int:
    """Write every chunk, handling partial raw writes without buffering all data."""
    total = 0
    for chunk in chunks:
        remaining = memoryview(chunk)
        while remaining:
            written = os.write(descriptor, remaining)
            if written == 0:
                raise BlockingIOError(errno.EIO, "staged output write made no progress")
            total += written
            remaining = remaining[written:]
    sync_file_descriptor(descriptor)
    return total
