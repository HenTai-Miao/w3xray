# Protected HM3W Offline Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pure-Python MPQ reader reproduce the confirmed StormLib 9.25 offline behavior for A801/A8E, close every failed-construction resource, and prove the result with automated, full-suite, and real-map regression evidence.

**Architecture:** Keep MPQ format decisions in `mpq_layout.py`, make bounded diagnostics consume the same pure header/offset rules, and move mutable file/mmap/temp ownership out of the 250-line `mpq.py` facade into a dedicated backing-store module. Preserve `MPQArchive._data` and every public caller while tightening protected-layout validation.

**Tech Stack:** CPython 3.14, pytest 9, stdlib `mmap`/`struct`/`tempfile`, existing pure-Python MPQ reader and CLI.

## Global Constraints

- Enable malformed-header compatibility only for files beginning with `HM3W` and MPQ `format_version == 0`.
- Never execute the legacy EXE/DLL, map scripts, loaders, or A8E's trailing KKWE payload.
- Keep all archive operations read-only and preserve current block, sector, decompression, and export budgets.
- Preserve UserData and ordinary MPQ behavior and the existing `MPQArchive` compatibility surface.
- Bound aligned main-header discovery to the first 16 MiB while preserving authoritative offset-zero UserData, and cap each materialized classic table at 262,144 readable entries.
- Do not add a StormLib runtime dependency.
- No changed hand-written Python module may exceed 250 pure LOC.
- Do not commit during this debugging workflow; use diff/test checkpoints and leave committing to the user.
- Do not modify any source map; prove this with before/after SHA-256.

## File Structure

- Modify `w3xtool/mpq_constants.py`: Warcraft map magic and 32-bit arithmetic constants only.
- Modify `w3xtool/mpq_layout.py`: shared classic-header normalization, paired-wrap validation, layout discovery, and table parsing.
- Modify `w3xtool/archive_diagnostics.py`: bounded header diagnosis using the same layout policy.
- Create `w3xtool/archive_layout_probe.py`: pure candidate-layout evidence and shared table-budget diagnosis.
- Create `w3xtool/mpq_storage.py`: sole owner of source handles, mmap objects, and fallback temporary copies.
- Modify `w3xtool/mpq.py`: facade delegates opening/closing to `MPQBackingStore` and closes it when construction fails.
- Modify `tests/test_mpq_protected_layout.py`: protected-layout positive and negative integration tests.
- Create `tests/test_mpq_storage.py`: deterministic resource-lifecycle tests.
- Modify `tests/test_mpq_robust.py` only if an existing lifecycle assertion belongs there; do not duplicate storage tests.

---

### Task 1: Complete the protected classic-layout contract

**Files:**
- Modify: `w3xtool/mpq_constants.py`
- Modify: `w3xtool/mpq_layout.py`
- Modify: `tests/test_mpq_protected_layout.py`

**Interfaces:**
- Consumes: `ArchiveBytes`, `MPQLayoutError`, and the existing `locate_mpq_layout(data)` public behavior.
- Produces: `normalize_classic_header_size(...) -> int` and `classic_table_offsets_use_wrap(...) -> bool` for Task 2; preserves and reuses the existing `resolve_classic_table_offset(...) -> int`.

- [x] **Step 1: Re-run the existing prototype tests as the starting checkpoint**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_protected_layout.py \
  tests/test_mpq_header.py \
  tests/test_mpq_user_data.py
```

Expected: the three existing protected-layout tests and all ordinary/UserData cases pass; record the exact count in `.debug-journal.md`.

- [x] **Step 2: Add the missing negative-layout tests**

Add this helper and tests to `tests/test_mpq_protected_layout.py` (retain Given/When/Then comments):

```python
def _with_only_hash_table_before_header(archive: bytes) -> bytes:
    fields = struct.unpack_from("<4sIIHHIIII", archive)
    hash_position, hash_count = fields[5], fields[7]
    hash_size = hash_count * 16
    protected_hash_position = _HM3W_HEADER_OFFSET - hash_size
    wrapped = bytearray(_HM3W_HEADER_OFFSET + len(archive))
    wrapped[:4] = b"HM3W"
    wrapped[_HM3W_HEADER_OFFSET:] = archive
    wrapped[protected_hash_position:_HM3W_HEADER_OFFSET] = archive[
        hash_position : hash_position + hash_size
    ]
    struct.pack_into("<I", wrapped, _HM3W_HEADER_OFFSET + 4, _PACK_HEADER_SIZE)
    struct.pack_into(
        "<I",
        wrapped,
        _HM3W_HEADER_OFFSET + 16,
        (protected_hash_position - _HM3W_HEADER_OFFSET) & 0xFFFFFFFF,
    )
    return bytes(wrapped)


def test_non_hm3w_archive_does_not_normalize_large_header(tmp_path: Path) -> None:
    source = bytearray(build_archive_bytes(b"war3map.j", ((0, b"script"),)))
    struct.pack_into("<I", source, 4, _A801_HEADER_SIZE)
    path = tmp_path / "not-hm3w.w3x"
    path.write_bytes(source)
    with pytest.raises(ValueError, match="头大小非法"):
        MPQArchive(str(path))


def test_hm3w_nonclassic_version_does_not_normalize_large_header(tmp_path: Path) -> None:
    source = bytearray(_with_hm3w_header_size(
        build_archive_bytes(b"war3map.j", ((0, b"script"),)),
        _A801_HEADER_SIZE,
    ))
    struct.pack_into("<H", source, _HM3W_HEADER_OFFSET + 12, 1)
    path = tmp_path / "nonclassic.w3x"
    path.write_bytes(source)
    with pytest.raises(ValueError, match="头大小非法"):
        MPQArchive(str(path))


def test_hm3w_header_smaller_than_32_bytes_is_rejected(tmp_path: Path) -> None:
    source = _with_hm3w_header_size(
        build_archive_bytes(b"war3map.j", ((0, b"script"),)),
        31,
    )
    path = tmp_path / "short-header.w3x"
    path.write_bytes(source)
    with pytest.raises(ValueError, match="头大小非法"):
        MPQArchive(str(path))


def test_hm3w_rejects_only_one_wrapped_table_offset(tmp_path: Path) -> None:
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "one-wrapped-table.w3x"
    path.write_bytes(_with_only_hash_table_before_header(source))
    with pytest.raises(ValueError, match="必须同时回绕"):
        MPQArchive(str(path))
```

Also add `import pytest` at the top.

- [x] **Step 3: Run the new tests and confirm the safety gap is red**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_protected_layout.py::test_hm3w_rejects_only_one_wrapped_table_offset
```

Expected before the paired-wrap check: FAIL because the mixed before/after-table layout opens instead of raising.

- [x] **Step 4: Implement shared normalization and paired-wrap policy**

Add `UINT32_MAX: Final = 0xFFFFFFFF` to `mpq_constants.py`. In `mpq_layout.py`, import it and replace inline policy with these functions:

```python
def normalize_classic_header_size(
    archive_offset: int,
    stored_header_size: int,
    file_size: int,
    *,
    protected_classic: bool,
) -> int:
    """Return the bounded effective header size for one classic candidate."""
    if stored_header_size < MPQ_HEADER_SIZE_V1 or (
        not protected_classic
        and archive_offset + stored_header_size > file_size
    ):
        raise MPQLayoutError(f"MPQ 头大小非法：{stored_header_size}")
    return MPQ_HEADER_SIZE_V1 if protected_classic else stored_header_size


def classic_table_offsets_use_wrap(
    archive_offset: int,
    hash_position: int,
    block_position: int,
    *,
    protected_classic: bool,
) -> bool:
    """Validate that a protected layout wraps both tables or neither table."""
    if not protected_classic:
        return False
    hash_wraps = archive_offset + hash_position > UINT32_MAX
    block_wraps = archive_offset + block_position > UINT32_MAX
    if hash_wraps != block_wraps:
        raise MPQLayoutError("MPQ hash/block 表偏移必须同时回绕")
    return hash_wraps
```

In `_parse_main_header`, call both helpers, preserve `protected_classic = data[:4] == WAR3_MAP_MAGIC and version == 0`, then resolve both offsets with `wrap_32bit=protected_classic`. Do not weaken existing count or file-boundary checks.

- [x] **Step 5: Run all layout tests green**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_protected_layout.py \
  tests/test_mpq_header.py \
  tests/test_mpq_user_data.py \
  tests/test_mpq_robust.py
```

Expected: exit 0 and no failures.

- [x] **Step 6: Record a diff checkpoint**

Run:

```bash
git diff --check -- \
  w3xtool/mpq_constants.py \
  w3xtool/mpq_layout.py \
  tests/test_mpq_protected_layout.py
```

Expected: no output and exit 0. Do not commit.

---

### Task 2: Make bounded diagnostics use the same policy

**Files:**
- Modify: `w3xtool/archive_diagnostics.py`
- Modify: `tests/test_mpq_protected_layout.py`
- Test: `tests/test_archive_diagnostics.py`

**Interfaces:**
- Consumes: Task 1's `normalize_classic_header_size` and `classic_table_offsets_use_wrap`.
- Produces: diagnosis evidence containing `effective_header_size=32`, `protected_classic=true`, and `table_offsets_wrapped=true|false` for coherent protected candidates.

- [x] **Step 1: Add red diagnostic-parity tests**

Add to `tests/test_mpq_protected_layout.py`:

```python
def test_protected_diagnosis_reports_normalized_header_and_wrap(tmp_path: Path) -> None:
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "diagnosis-evidence.w3x"
    path.write_bytes(_with_tables_before_header(source))
    diagnosis = diagnose_archive_open(str(path), ValueError("later failure"))
    assert diagnosis.kind is ArchiveDiagnosisKind.READ_ERROR
    assert "effective_header_size=32" in diagnosis.evidence
    assert "protected_classic=true" in diagnosis.evidence
    assert "table_offsets_wrapped=true" in diagnosis.evidence


def test_non_hm3w_large_header_is_diagnosed_as_damage(tmp_path: Path) -> None:
    source = bytearray(build_archive_bytes(b"war3map.j", ((0, b"script"),)))
    struct.pack_into("<I", source, 4, _A801_HEADER_SIZE)
    path = tmp_path / "diagnostic-not-hm3w.w3x"
    path.write_bytes(source)
    diagnosis = diagnose_archive_open(str(path))
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert any("头大小非法" in item for item in diagnosis.evidence)


def test_diagnosis_rejects_only_one_wrapped_table_offset(tmp_path: Path) -> None:
    source = build_archive_bytes(b"war3map.j", ((0, b"script"),))
    path = tmp_path / "diagnostic-one-wrap.w3x"
    path.write_bytes(_with_only_hash_table_before_header(source))
    diagnosis = diagnose_archive_open(str(path))
    assert diagnosis.kind is ArchiveDiagnosisKind.TABLE_DAMAGE
    assert any("必须同时回绕" in item for item in diagnosis.evidence)
```

- [x] **Step 2: Run the diagnostic tests red**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_protected_layout.py::test_protected_diagnosis_reports_normalized_header_and_wrap \
  tests/test_mpq_protected_layout.py::test_non_hm3w_large_header_is_diagnosed_as_damage \
  tests/test_mpq_protected_layout.py::test_diagnosis_rejects_only_one_wrapped_table_offset
```

Expected before parity implementation: FAIL because evidence is missing and non-HM3W/mixed-wrap candidates are labeled structurally valid.

- [x] **Step 3: Reuse the layout helpers in `_validate_candidate`**

Import the Task 1 helpers and `MPQLayoutError`. Rename the boolean passed from `_diagnose_readable` to `war3_map`, derive `protected_classic = war3_map and format_version == 0`, then apply:

```python
try:
    effective_header_size = normalize_classic_header_size(
        offset,
        header_size,
        file_size,
        protected_classic=protected_classic,
    )
    table_offsets_wrapped = classic_table_offsets_use_wrap(
        offset,
        hash_pos,
        block_pos,
        protected_classic=protected_classic,
    )
except MPQLayoutError as exc:
    return fields + (f"layout_error={exc}",)

fields += (
    f"effective_header_size={effective_header_size}",
    f"protected_classic={str(protected_classic).lower()}",
    f"table_offsets_wrapped={str(table_offsets_wrapped).lower()}",
)
```

Resolve offsets with `wrap_32bit=protected_classic`; retain the 16 MiB scan limit and 32-byte reads.

- [x] **Step 4: Run diagnostic and layout suites green**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_protected_layout.py \
  tests/test_archive_diagnostics.py \
  tests/test_mpq_header.py
```

Expected: exit 0; existing missing/permission/unsupported/scan-budget classifications remain unchanged.

- [x] **Step 5: Verify diagnosis remains bounded**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_archive_diagnostics.py::test_probe_uses_only_bounded_header_reads \
  tests/test_archive_diagnostics.py::test_header_beyond_sixteen_mib_scan_window_is_ignored
```

Expected: 2 passed.

---

### Task 3: Extract backing-store ownership and close failed construction

**Files:**
- Create: `w3xtool/mpq_storage.py`
- Create: `tests/test_mpq_storage.py`
- Modify: `w3xtool/mpq.py`
- Test: `tests/test_mpq_robust.py`

**Interfaces:**
- Produces: mutable resource owner `MPQBackingStore`, `open_mpq_backing(path: str) -> MPQBackingStore`.
- Preserves: `MPQArchive._data`, `_file`, `_tmp`, `close()`, and context-manager behavior.

- [x] **Step 1: Add a red test against the existing `MPQArchive` interface**

Add `builtins`, `mmap`, `Path`, and `pytest` imports plus this module-level test to `tests/test_mpq_robust.py` before creating the new storage module:

```python
def test_constructor_failure_closes_real_mmap_and_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large-invalid.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    real_mmap = mmap.mmap
    real_open = builtins.open
    mapped_objects: list[mmap.mmap] = []
    source_handles = []

    def tracking_mmap(*args, **kwargs):
        mapped = real_mmap(*args, **kwargs)
        mapped_objects.append(mapped)
        return mapped

    def tracking_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        if Path(file) == path:
            source_handles.append(handle)
        return handle

    monkeypatch.setattr(mmap, "mmap", tracking_mmap)
    monkeypatch.setattr(builtins, "open", tracking_open)

    with pytest.raises(ValueError, match="没找到 MPQ 头"):
        MPQArchive(str(path))

    assert len(mapped_objects) == 1 and mapped_objects[0].closed
    assert len(source_handles) == 1 and source_handles[0].closed
```

- [x] **Step 2: Run the existing-interface lifecycle test red**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_robust.py::test_constructor_failure_closes_real_mmap_and_handle
```

Expected before the refactor: FAIL because the captured mmap and source handle remain open after `MPQArchive.__init__` raises.

- [x] **Step 3: Add backing-store unit tests**

Create `tests/test_mpq_storage.py`:

```python
from __future__ import annotations

import mmap
from pathlib import Path

import pytest

from w3xtool.mpq import MPQArchive
from w3xtool.mpq_layout import MPQLayoutError
from w3xtool.mpq_storage import MPQBackingStore, open_mpq_backing


def test_backing_store_close_releases_real_mmap_and_handle(tmp_path: Path) -> None:
    path = tmp_path / "large-invalid.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    store = open_mpq_backing(str(path))
    mapped = store.data
    source_handle = store.handle
    assert isinstance(mapped, mmap.mmap)
    assert source_handle is not None
    store.close()
    store.close()
    assert mapped.closed
    assert source_handle.closed


def test_backing_store_retains_mmap_when_exported_buffer_blocks_close(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    store = open_mpq_backing(str(path))
    mapped = store.data
    assert isinstance(mapped, mmap.mmap)
    exported = memoryview(mapped)
    store.close()
    assert store.data is mapped
    assert not mapped.closed
    exported.release()
    store.close()
    assert mapped.closed


def test_archive_constructor_closes_backing_when_layout_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large-invalid.w3x"
    with path.open("wb") as handle:
        handle.truncate(41 * 1024 * 1024)
    store = open_mpq_backing(str(path))
    mapped = store.data
    source_handle = store.handle
    monkeypatch.setattr("w3xtool.mpq.open_mpq_backing", lambda _path: store)
    with pytest.raises(MPQLayoutError):
        MPQArchive(str(path))
    assert isinstance(mapped, mmap.mmap) and mapped.closed
    assert source_handle is not None and source_handle.closed


def test_archive_constructor_removes_fallback_copy_when_layout_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary = tmp_path / "fallback.w3x"
    temporary.write_bytes(b"not an mpq")
    store = MPQBackingStore(
        data=temporary.read_bytes(),
        handle=None,
        temporary_path=str(temporary),
    )
    monkeypatch.setattr("w3xtool.mpq.open_mpq_backing", lambda _path: store)
    with pytest.raises(MPQLayoutError):
        MPQArchive("source.w3x")
    assert not temporary.exists()


def test_fallback_copy_is_removed_when_second_open_raises_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    from w3xtool import mpq_storage

    source = tmp_path / "source.w3x"
    source.write_bytes(b"source")
    temporary = tmp_path / "owned-copy.w3x"
    calls = 0

    def failing_open(_path: str, *, temporary_path: str | None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("direct open denied")
        raise ValueError("mmap rejected")

    def owned_mkstemp(*, suffix: str):
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        return descriptor, str(temporary)

    monkeypatch.setattr(mpq_storage, "_open_path", failing_open)
    monkeypatch.setattr(mpq_storage.tempfile, "mkstemp", owned_mkstemp)
    with pytest.raises(ValueError, match="mmap rejected"):
        open_mpq_backing(str(source))
    assert calls == 2
    assert not temporary.exists()
```

- [x] **Step 4: Run the new module tests red**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_mpq_storage.py
```

Expected before the module exists: collection fails with `ModuleNotFoundError: w3xtool.mpq_storage`.

- [x] **Step 5: Implement `MPQBackingStore`**

Create `w3xtool/mpq_storage.py` with this complete ownership surface:

```python
"""Owned byte storage for MPQ archives."""

from __future__ import annotations

import mmap
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import BinaryIO, Final

type ArchiveBytes = bytes | mmap.mmap

_MMAP_THRESHOLD: Final = 40 * 1024 * 1024


@dataclass(slots=True)  # noqa: MUTABLE_OK - this object owns closeable state.
class MPQBackingStore:
    """Own mutable archive bytes, an optional source handle, and a temp copy."""

    data: ArchiveBytes
    handle: BinaryIO | None
    temporary_path: str | None

    def close(self) -> None:
        """Release every owned resource; repeated calls are harmless."""
        if isinstance(self.data, mmap.mmap):
            try:
                self.data.close()
            except (BufferError, OSError):
                return
            except ValueError:
                pass
            self.data = b""
        if self.handle is not None:
            try:
                self.handle.close()
            except OSError:
                return
            self.handle = None
        if self.temporary_path is not None:
            try:
                os.remove(self.temporary_path)
            except FileNotFoundError:
                self.temporary_path = None
            except OSError:
                return
            else:
                self.temporary_path = None


def open_mpq_backing(path: str) -> MPQBackingStore:
    """Open the source, falling back to an owned copy for OS open failures."""
    try:
        return _open_path(path, temporary_path=None)
    except (OSError, ValueError):
        descriptor, temporary_path = tempfile.mkstemp(
            suffix=os.path.splitext(path)[1] or ".w3x",
        )
        os.close(descriptor)
        try:
            shutil.copyfile(path, temporary_path)
            store = _open_path(temporary_path, temporary_path=temporary_path)
        except (OSError, ValueError):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
            raise
        if store.handle is None:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                store.temporary_path = None
            except OSError:
                pass
            else:
                store.temporary_path = None
        return store


def _open_path(path: str, *, temporary_path: str | None) -> MPQBackingStore:
    size = os.path.getsize(path)
    handle = open(path, "rb")
    if size <= _MMAP_THRESHOLD:
        try:
            data = handle.read()
        finally:
            handle.close()
        return MPQBackingStore(data=data, handle=None, temporary_path=temporary_path)
    try:
        data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError):
        handle.close()
        raise
    return MPQBackingStore(data=data, handle=handle, temporary_path=temporary_path)
```

- [x] **Step 6: Delegate `MPQArchive` construction and cleanup**

Import `MPQBackingStore` and `open_mpq_backing` in `mpq.py`. Replace `_open` and inline temp-copy logic with:

```python
self._backing: MPQBackingStore = open_mpq_backing(path)
self._sync_backing()
initialized = False
try:
    self._parse_header()
    self._read_tables()
    self._names = None
    initialized = True
finally:
    if not initialized:
        self.close()
```

Replace `close()` internals and remove `_open()`:

```python
def close(self) -> None:
    """Release the owned backing store; repeated calls are harmless."""
    self._backing.close()
    self._sync_backing()

def _sync_backing(self) -> None:
    self._data = self._backing.data
    self._file = self._backing.handle
    self._tmp = self._backing.temporary_path
```

Keep `__enter__`, `__exit__`, and every map-reading method unchanged. If a test constructs `MPQArchive` through `object.__new__` and calls `close`, initialize a backing store in that test rather than adding speculative `getattr` branches.

- [x] **Step 7: Run lifecycle and MPQ regression tests green**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_storage.py \
  tests/test_mpq_robust.py \
  tests/test_mpq_header.py \
  tests/test_mpq_protected_layout.py
```

Expected: exit 0; real mmap/handle/temp assertions pass without `ResourceWarning`.

- [x] **Step 8: Check file boundaries and source quality**

Run:

```bash
for file in \
  w3xtool/mpq.py \
  w3xtool/mpq_storage.py \
  w3xtool/mpq_layout.py \
  w3xtool/archive_diagnostics.py; do
  count=$(awk '!/^[[:space:]]*$/ && !/^[[:space:]]*#/' "$file" | wc -l)
  echo "$count $file"
  test "$count" -le 250
done
git diff --check
! rg -n '[[:blank:]]+$' w3xtool/mpq_storage.py tests/test_mpq_storage.py
git diff --no-index -- /dev/null w3xtool/mpq_storage.py || test "$?" = 1
git diff --no-index -- /dev/null tests/test_mpq_storage.py || test "$?" = 1
```

Expected: every count is at most 250, `mpq.py` is below its previous 250-line ceiling, tracked and untracked files have no trailing whitespace, and both new files are explicitly displayed for review.

---

### Task 4: Focused, full-suite, and static verification

**Files:**
- Verify only; fix failures in the owning file from Tasks 1–3.

**Interfaces:**
- Consumes: all production/test changes.
- Produces: current command evidence with no failures.

- [x] **Step 1: Run the complete MPQ/diagnostic/security focus set**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_mpq_protected_layout.py \
  tests/test_mpq_header.py \
  tests/test_mpq_user_data.py \
  tests/test_mpq_robust.py \
  tests/test_mpq_enumerate.py \
  tests/test_mpq_names_locale.py \
  tests/test_archive_diagnostics.py \
  tests/test_security_boundaries.py \
  tests/test_decompress_limits.py \
  tests/test_mpq_storage.py
```

Expected: exit 0 with no failed/error tests.

- [x] **Step 2: Run syntax and whitespace gates**

Run:

```bash
.venv/bin/python -m compileall -q w3xtool tests
git diff --check
! rg -n '[[:blank:]]+$' \
  w3xtool/mpq_storage.py \
  tests/test_mpq_storage.py \
  tests/test_mpq_protected_layout.py \
  docs/superpowers/specs/2026-07-12-protected-hm3w-offline-compatibility-design.md \
  docs/superpowers/plans/2026-07-12-protected-hm3w-offline-compatibility.md
```

Expected: all commands exit 0 with no output. This repository has no configured lint/type-check entrypoint, so the documented static gate is syntax compilation, exact diff/whitespace inspection, import/runtime tests, and the pure-LOC ceiling.

- [x] **Step 3: Run the full project suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: exit 0; every non-platform test passes and existing platform-dependent skips remain explicitly reported.

- [x] **Step 4: Inspect the complete diff for scope**

Run:

```bash
git status --short
git diff --stat
git diff -- \
  w3xtool/mpq_constants.py \
  w3xtool/mpq_layout.py \
  w3xtool/archive_diagnostics.py \
  w3xtool/mpq_storage.py \
  w3xtool/mpq.py \
  tests/test_mpq_protected_layout.py \
  tests/test_mpq_storage.py
for new_file in \
  w3xtool/mpq_storage.py \
  tests/test_mpq_storage.py \
  tests/test_mpq_protected_layout.py \
  docs/superpowers/specs/2026-07-12-protected-hm3w-offline-compatibility-design.md \
  docs/superpowers/plans/2026-07-12-protected-hm3w-offline-compatibility.md; do
  if ! git ls-files --error-unmatch "$new_file" >/dev/null 2>&1; then
    git diff --no-index -- /dev/null "$new_file" || test "$?" = 1
  fi
done
```

Expected: tracked and untracked changes are all displayed; only approved code, tests, spec, and plan are present, with no map, binary, cache, or reverse-engineering output.

---

### Task 5: Original-22 and current-27 real-map regression

**Files:**
- Read only: `/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps/`
- Temporary evidence: `/tmp/war3-xg-map-baseline-current.sha256`, `/tmp/war3-xg-map-baseline-27.sha256`, `/tmp/war3-xg-map-after-27.sha256`, `/tmp/war3-xg-map-audit-final/`

**Interfaces:**
- Consumes: public `main.py cli` and `w3xtool.api.load_map`.
- Produces: 27 exit-code logs, exact protected-map assertions, and byte-identity proof.

- [x] **Step 1: Capture and verify the real-map baselines before loading**

Run in `zsh`:

```bash
MAP_ROOT='/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps'
find "$MAP_ROOT" -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 \
  > /tmp/war3-xg-map-baseline-27.sha256
test "$(wc -l < /tmp/war3-xg-map-baseline-27.sha256 | tr -d ' ')" = 27
test "$(wc -l < /tmp/war3-xg-map-baseline-current.sha256 | tr -d ' ')" = 22
shasum -a 256 -c /tmp/war3-xg-map-baseline-current.sha256
while IFS= read -r entry; do
  original_path=${entry#*  }
  test -f "$original_path"
  grep -Fq "  $original_path" /tmp/war3-xg-map-baseline-27.sha256
done < /tmp/war3-xg-map-baseline-current.sha256
```

Expected: the manifests contain exactly 27 and 22 entries, every original checksum prints `OK`, and every original path is present in the current manifest.

- [x] **Step 2: Run the original 22-map manifest through the real CLI**

Run:

```bash
rm -rf /tmp/war3-xg-map-audit-final
mkdir -p /tmp/war3-xg-map-audit-final/original22
failed=0
while IFS= read -r entry; do
  map=${entry#*  }
  name=$(basename "$map")
  if ! .venv/bin/python main.py cli "$map" \
      > "/tmp/war3-xg-map-audit-final/original22/${name}.log" 2>&1; then
    echo "FAIL $name"
    failed=1
  else
    echo "PASS $name"
  fi
done < /tmp/war3-xg-map-baseline-current.sha256
test "$failed" = 0
test "$(find /tmp/war3-xg-map-audit-final/original22 -type f -name '*.log' | wc -l | tr -d ' ')" = 22
```

Expected: 22 `PASS` lines, no `FAIL`, and 22 original-manifest logs.

- [x] **Step 3: Run every current map through the real CLI**

Run:

```bash
mkdir -p /tmp/war3-xg-map-audit-final/current27
failed=0
while IFS= read -r -d '' map; do
  name=$(basename "$map")
  if ! .venv/bin/python main.py cli "$map" \
      > "/tmp/war3-xg-map-audit-final/current27/${name}.log" 2>&1; then
    echo "FAIL $name"
    failed=1
  else
    echo "PASS $name"
  fi
done < <(find "$MAP_ROOT" -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 | sort -z)
test "$failed" = 0
test "$(find /tmp/war3-xg-map-audit-final/current27 -type f -name '*.log' | wc -l | tr -d ' ')" = 27
```

Expected: 27 `PASS` lines, no `FAIL`, and 27 current-corpus logs.

- [x] **Step 4: Assert the two protected-map outcomes and exact members**

Run:

```bash
export A801="$MAP_ROOT/dz/rpg/A80167E5296276AD606B310D4B54F61F.w3x"
export A8E="$MAP_ROOT/dz/rpg/A8E238ED8C50ECB52657B7265B01D4BA.w3x"
.venv/bin/python -c '
from w3xtool.api import load_map
from w3xtool.mpq import MPQArchive
import os
a801 = load_map(os.environ["A801"])
a8e = load_map(os.environ["A8E"])
required_a801 = {
    "war3map.wts", "war3map.w3t", "war3map.w3u",
    "war3map.w3a", "war3map.w3q", "war3map.j",
}
expected_a8e = {"war3map.w3i", "war3map.mmp", "war3mapMap.blp", "war3map.j"}
assert len(a801.all_files) == 22, len(a801.all_files)
assert required_a801 <= set(a801.all_files), a801.all_files
assert sum(a801.category_counts().values()) == 2507, a801.category_counts()
assert a8e.name == "轮回世界", a8e.name
assert set(a8e.all_files) == expected_a8e, a8e.all_files
assert sum(a8e.category_counts().values()) == 0, a8e.category_counts()
assert a8e.object_source_counts == {}, a8e.object_source_counts
with MPQArchive(os.environ["A801"]) as archive:
    for name in required_a801:
        assert archive.has_file(name), name
        assert archive.read_file(name), name
with MPQArchive(os.environ["A8E"]) as archive:
    for name in expected_a8e:
        assert archive.has_file(name), name
print("A801", a801.name, len(a801.all_files), sum(a801.category_counts().values()))
print("A8E", a8e.name, len(a8e.all_files), sum(a8e.category_counts().values()))
'
```

Expected: both assertions pass and two summary lines print.

- [x] **Step 5: Prove no source map changed**

Run:

```bash
find "$MAP_ROOT" -type f \( -iname '*.w3x' -o -iname '*.w3m' -o -iname '*.w3n' \) -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 \
  > /tmp/war3-xg-map-after-27.sha256
cmp /tmp/war3-xg-map-baseline-27.sha256 /tmp/war3-xg-map-after-27.sha256
shasum -a 256 -c /tmp/war3-xg-map-baseline-current.sha256
```

Expected: `cmp` exits 0 and all original-22 entries print `OK`.

---

### Task 6: Final review, cleanup, and completion audit

**Files:**
- Review all changed files and the approved spec/plan.
- Remove ignored `.debug-journal.md` and temporary evidence after recording final command results.

**Interfaces:**
- Produces: a clean scoped diff and requirement-by-requirement proof suitable for marking the goal complete.

- [x] **Step 1: Run post-implementation review**

Invoke `review-work` against the exact goal and changed files. Resolve every confirmed correctness, security, lifecycle, and regression issue with a new red→green test before proceeding.

Review-confirmed hardening to verify in this step:

- single-open nonblocking regular-file storage with descriptor-sized reads;
- cleanup errors preserve the primary fallback-open exception;
- 16 MiB main-header scan and 262,144 readable-entry table budgets;
- diagnostic format/range evidence and explicit unsupported marker;
- candidate validation split into `archive_layout_probe.py` to preserve the 250-pure-LOC ceiling.

- [x] **Step 2: Re-run affected tests after review fixes**

Run the Task 4 focused command, then `.venv/bin/python -m pytest -q`, then both Task 5 CLI loops (original 22 and current 27), exact protected-map assertions, and checksum comparison.

Expected: every gate remains green after review changes.

Recorded post-hardening result: focused `81 passed`; full `1051 passed, 4 skipped, 1 subtests passed`; original22 `22/22`; current27 `27/27`; exact protected assertions passed; baseline/after manifest SHA-256 remained identical.

- [x] **Step 3: Clean debug-only artifacts**

Remove only paths recorded in `.debug-journal.md`:

```bash
rm -rf /tmp/war3-xg-map-audit-current /tmp/war3-xg-map-audit-final
rm -f /tmp/war3-xg-map-baseline-current.sha256 \
  /tmp/war3-xg-map-baseline-27.sha256 \
  /tmp/war3-xg-map-after-27.sha256
rm -f .debug-journal.md
```

Then remove the `.debug-journal.md` entry from `.git/info/exclude` only if this debugging session added it.

- [x] **Step 4: Perform the final scope and completion audit**

Run:

```bash
git status --short
git diff --check
git diff --stat
```

Verify each approved spec requirement against command evidence. Expected: only scoped source/tests/spec/plan changes remain, all explicit gates have direct evidence, and no required work is missing.

- [x] **Step 5: Mark the active goal complete only after every gate is proven**

Call the goal completion mechanism only when Tasks 1–6 are fully checked and no review issue remains. Do not commit, stage, or push unless the user separately asks.
