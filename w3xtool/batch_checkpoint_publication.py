"""Error-translating boundary for authoritative global checkpoints."""

from __future__ import annotations

from .batch_configuration import BatchOutputError
from .batch_global_publication import publish_global_generation
from .batch_models import BatchState
from .batch_output_lock import BatchOutputLease


def publish_batch_checkpoint(
    output_root: str,
    state: BatchState,
    cache_text: str,
    diagnostics_text: str,
    lease: BatchOutputLease | None = None,
) -> None:
    """Publish one generation or expose a stable batch-output failure."""
    try:
        _ = publish_global_generation(
            output_root,
            state,
            cache_text,
            diagnostics_text,
            lease,
        )
    except OSError as exc:
        raise BatchOutputError(
            ".w3xray-global",
            str(exc),
        ) from exc


__all__ = ("publish_batch_checkpoint",)
