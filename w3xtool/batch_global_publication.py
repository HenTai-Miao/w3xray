from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
import shutil
from typing import Final
from uuid import uuid4

from .batch_global_io import (
    format_global_manifest,
    format_global_pointer,
    parse_global_pointer,
)
from .batch_global_payloads import build_global_payloads
from .batch_global_models import (
    GLOBAL_MANIFEST_NAME,
    GLOBAL_PAYLOAD_NAMES,
    GLOBAL_POINTER_NAME,
    GLOBAL_ROOT_NAME,
    GLOBAL_SCHEMA_VERSION,
    GlobalArtifact,
    GlobalGeneration,
    GlobalManifest,
    GlobalPointer,
    GlobalPublicationError,
)
from .batch_global_validation import validate_global_generation
from .batch_models import BATCH_SCHEMA_VERSION, BatchState
from .batch_output_lock import (
    BatchOutputLease,
    hold_batch_output_lock,
    lease_is_current,
)
from .bounded_file import read_bounded_regular_file
from .durable_io import sync_directory
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus


_MAX_POINTER_BYTES: Final = 64 * 1024


def publish_global_generation(
    output_root: str | Path,
    state: BatchState,
    cache_text: str,
    diagnostics_text: str,
    lease: BatchOutputLease | None = None,
) -> GlobalGeneration:
    """Commit all global payloads, select them, then update compatibility mirrors."""
    if lease is None:
        with hold_batch_output_lock(output_root) as owned:
            return _publish_global_generation_locked(
                output_root,
                state,
                cache_text,
                diagnostics_text,
                owned,
            )
    return _publish_global_generation_locked(
        output_root,
        state,
        cache_text,
        diagnostics_text,
        lease,
    )


def _publish_global_generation_locked(
    output_root: str | Path,
    state: BatchState,
    cache_text: str,
    diagnostics_text: str,
    lease: BatchOutputLease,
) -> GlobalGeneration:
    if not lease_is_current(lease, output_root):
        raise GlobalPublicationError("batch output lease is not current")
    output, global_root, generations = _prepare_roots(Path(output_root))
    generation_id = uuid4().hex
    stage = global_root / f".w3xray-global-stage-{generation_id}"
    destination = generations / generation_id
    bundle = build_global_payloads(output, state, cache_text, diagnostics_text)
    payloads = bundle.payloads
    stage.mkdir(mode=0o700)
    try:
        sync_directory(global_root)
        for name, text in payloads.items():
            _write_text(stage, name, text)
        manifest = _manifest(generation_id, payloads)
        manifest_text = format_global_manifest(manifest)
        _write_text(stage, GLOBAL_MANIFEST_NAME, manifest_text)
        sync_directory(stage)
        os.replace(stage, destination)
        sync_directory(generations)
        generation = validate_global_generation(destination)
        if generation is None:
            raise GlobalPublicationError("published global generation is invalid")
        _publish_pointer(global_root, generation)
        selected = load_current_generation(output)
        if selected != generation:
            raise GlobalPublicationError("global current pointer failed validation")
        _publish_compatibility_mirrors(output, payloads)
        return generation
    finally:
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
            sync_directory(global_root)


def load_current_generation(output_root: str | Path) -> GlobalGeneration | None:
    """Load only the exact generation selected by a strict current pointer."""
    global_root = Path(output_root, GLOBAL_ROOT_NAME)
    pointer_path = global_root / GLOBAL_POINTER_NAME
    if global_root.is_symlink() or not global_root.is_dir():
        return None
    try:
        payload, _identity = read_bounded_regular_file(pointer_path, _MAX_POINTER_BYTES)
        pointer = parse_global_pointer(payload.decode("utf-8"))
    except OSError, UnicodeError, ValueError:
        return None
    directory = global_root / "generations" / pointer.generation_id
    return validate_global_generation(directory, pointer.manifest_sha256)


def load_current_batch_state(output_root: str | Path) -> BatchState | None:
    """Return state only through the validated authoritative pointer."""
    generation = load_current_generation(output_root)
    return None if generation is None else generation.state


def _prepare_roots(output: Path) -> tuple[Path, Path, Path]:
    if output.is_symlink():
        raise GlobalPublicationError("output root is a symlink")
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink() or not output.is_dir():
        raise GlobalPublicationError("output root is unsafe")
    global_root = output / GLOBAL_ROOT_NAME
    generations = global_root / "generations"
    if global_root.is_symlink() or generations.is_symlink():
        raise GlobalPublicationError("global publication root is a symlink")
    global_root.mkdir(exist_ok=True)
    generations.mkdir(exist_ok=True)
    if not global_root.is_dir() or not generations.is_dir():
        raise GlobalPublicationError("global publication root is unsafe")
    sync_directory(output)
    sync_directory(global_root)
    return output, global_root, generations


def _manifest(
    generation_id: str,
    payloads: Mapping[str, str],
) -> GlobalManifest:
    artifacts = tuple(
        sorted(
            (
                GlobalArtifact(
                    name,
                    len(text.encode("utf-8")),
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                for name, text in payloads.items()
            ),
            key=lambda artifact: artifact.name.casefold(),
        )
    )
    return GlobalManifest(
        GLOBAL_SCHEMA_VERSION,
        generation_id,
        BATCH_SCHEMA_VERSION,
        artifacts,
        sum(item.size for item in artifacts),
    )


def _publish_pointer(
    global_root: Path,
    generation: GlobalGeneration,
) -> None:
    pointer = GlobalPointer(
        GLOBAL_SCHEMA_VERSION,
        generation.generation_id,
        generation.manifest_sha256,
    )
    _write_text(global_root, GLOBAL_POINTER_NAME, format_global_pointer(pointer))


def _publish_compatibility_mirrors(
    output_root: Path,
    payloads: Mapping[str, str],
) -> None:
    for name in GLOBAL_PAYLOAD_NAMES:
        _write_text(output_root, name, payloads[name])


def _write_text(root: Path, name: str, text: str) -> None:
    result = write_text_safely(str(root), name, text)
    if result.status is not SafeWriteStatus.WRITTEN:
        raise GlobalPublicationError(
            f"cannot publish {name}: {result.error or result.status.value}"
        )


__all__ = (
    "GlobalGeneration",
    "GlobalPublicationError",
    "load_current_batch_state",
    "load_current_generation",
    "publish_global_generation",
)
