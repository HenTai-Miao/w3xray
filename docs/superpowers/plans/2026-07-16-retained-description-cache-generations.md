# Retained Trusted-Description Cache Generations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every recursive-deletion authority from trusted-description-cache publication, atomically preserve displaced or failed generations under typed retained names, and expose those retained records through migration and operator integrity evidence.

**Architecture:** Add a small immutable retention model and one descriptor-anchored, atomic no-replace move primitive. Thread that primitive through first publication, replacement commit, rollback/recovery, and final-stage handling so the active five-file cache format is unchanged while every non-active directory is preserved. Return retained records from publication and migration, print them at the CLI, and amend the parent schema-5 plan so future integrity acceptance counts transient and retained artifacts on separate axes.

**Tech Stack:** Python 3.14, `pathlib`, frozen/slots dataclasses, `StrEnum`, existing Darwin/Linux `rename_noreplace` and `rename_exchange` primitives, uv, pytest, Ruff, basedpyright.

**Supporting specification:** `docs/superpowers/specs/2026-07-16-retained-description-cache-generations-design.md`

## Global Constraints

- Never call `shutil.rmtree`, `os.rmdir`, or any recursive deletion path for a stage, backup, output, rollback, recovery, or retained trusted-description-cache generation.
- Allocate exactly one cryptographically random 32-character lowercase hexadecimal transaction identifier per publication attempt.
- Keep transient names exactly `.w3xray-description-cache-stage-<transaction-id>` and `.w3xray-description-cache-backup-<transaction-id>`.
- Keep retained names exactly `.w3xray-description-cache-retained-<transaction-id>-<role>` where role is one of `previous`, `failed-stage`, `failed-output`, or `recovery`.
- Every rename is descriptor-relative, atomic, and no-replace; compare `(device, inode)` before and after every retention move.
- Every atomic-move return or ordinary exception, including `FileExistsError`, enters the same source/destination postcondition proof; exception class never proves that a move did not happen, and every reachable side remains retained or transient evidence.
- A recovery move is clean only when its source is readably absent and its destination has the exact expected identity; a source name reacquired after a normal-return move is preserved as transient evidence beside the recovery record and forces typed `NEEDS_CONTEXT`.
- Once the exact old generation has been observed at its intended `previous` retained name, rollback is forbidden even if parent fsync, public-parent binding, or final evidence proof later fails; preserve `output=new` plus `previous=old` and return typed `NEEDS_CONTEXT`.
- Keep the publication-parent descriptor open across descriptor-relative `mkdir`. After the
  first no-follow stage `open` and descriptor-identity capture succeeds, keep that captured
  stage descriptor and the parent descriptor open through the last build, validation,
  rename, rollback, or retention action; stage construction never re-resolves either
  pathname after capture.
- POSIX `mkdirat` returns neither a descriptor nor the created inode. The threat model
  therefore requires publication-parent permissions or cooperation to prevent a
  same-permission process from replacing the stage leaf between `mkdirat` return and the
  first successful no-follow stage-open/identity capture. Repeating named `stat` and
  descriptor comparisons cannot recover creation provenance if one replacement survives
  both. Zero-write and byte-for-byte-untouched guarantees start only at successful held-stage
  capture; closing this interval against a hostile peer is an explicit platform non-goal.
- Create every stage payload as an exclusive, no-follow regular-file leaf relative to the held stage descriptor, synchronize that file descriptor, and validate the completed generation through the same held stage descriptor.
- Every held-stage, active, and expected-previous proof snapshots all five owned leaves before and after a complete read/hash round; final success performs one terminal set-wide reread/reproof, including device, inode, size, `mtime_ns`, `ctime_ns`, mode, and SHA-256, rather than relying on directory inode or per-file stability alone.
- Generation state retains each complete `os.stat_result` for the existing anchored reader, while stability compares only device, inode, size, `mtime_ns`, `ctime_ns`, and mode; writer, snapshot, read, hash, and proof tuples all use one UTF-8 filename-byte owned-inventory order.
- The terminal success proof snapshots both private stage/backup names before and after that set-wide read; if either appears, independently normalize both again and forbid success.
- Every ordinary `Exception` boundary after parent/stage mutation converts to typed evidence; stage creation, absent-output post-install proof, durable retention, each private-name attempt, and the bound transaction all preserve evidence independently, while process-control exceptions remain uncaught.
- Only the descriptor-relative stage `mkdir` call classifies `FileExistsError` as a name collision; every exception after that call returns is a post-creation normalization failure.
- Every required `except Exception` carries `# noqa: BROAD_EXCEPT_OK - <specific evidence reason>`, immediately converts/re-proves and re-raises or returns an internal attempt value, and is limited to the explicitly enumerated lifecycle boundaries in Task 2 Step 10; no catch swallows a cause or broadens to `BaseException`. Every exact caught failure enters the surfaced error's `failures` tuple in operation-event order with identity de-duplication, even when it is also the one explicit `__cause__`; equal type/text never collapses distinct objects.
- Never overwrite, auto-load, auto-promote, auto-delete, or garbage-collect a retained sibling.
- Preservation outranks namespace normalization: success always has zero transient names, but when every legal retained target is occupied, the held parent binding is lost, or the filesystem rejects atomic no-replace, preserve every reachable object and return typed `NEEDS_CONTEXT` with the remaining transient reported as an integrity violation.
- An absent stage leaf is considered consumed only when the held stage identity is exact at active output or one of the transaction's legal retained names; otherwise finalization reports the distinct still-open held identity.
- Every stage-location proof scans active output plus every legal retained name, keeps the unique held-stage location separate from unrelated current-name evidence, and adds a held-stage transient only when no unique exact location exists.
- Every stage-location proof receives already published retained evidence, scans `output`, `previous`, `failed-stage`, `failed-output`, and `recovery` twice in fixed order, rejects any between-scan change, and makes the clean-path public-parent binding check its final filesystem operation.
- Close the held stage and parent descriptors independently through one typed evidence boundary; close faults never replace an in-flight publication subtype/evidence, and a close fault after nominal success returns typed `NEEDS_CONTEXT` with the last proved retained records.
- A retained `previous` is `valid-cache` only when its root contains exactly the five owned regular-file leaves, with no missing, extra, or nested entry; a stable inventory mismatch is `invalid-previous`/exit `1`.
- An exact retained `previous` of any non-directory kind is `unsafe-object`/exit `1`, never `partial-evidence`; only the three partial roles may produce ordinary `partial-evidence`, and their symlink/special objects remain unsafe.
- Preserve the active cache marker, manifest, three TSV payloads, source replay, public `load_trusted_description_cache(root)` behavior, and batch dependency fingerprint unchanged.
- Preserve source maps and historical outputs as read-only; do not execute map scripts, EXE/DLL files, or `Game.dll`, and do not read game memory.
- Every production change follows real RED → GREEN → refactor; every edited or created hand-written Python module remains at or below 250 pure LOC.
- Changed Python annotations contain neither `Any` nor `object`; stable generation state uses exact aliases or frozen typed values so the mandatory no-excuse gate can pass.
- Do not grow `w3xtool/description_cache_publication_replacement.py`, `w3xtool/description_cache_migration.py`, or `tests/test_description_cache_publication.py` without moving the new responsibility into a focused file first.
- No exception boundary may execute `raise error from error` or overwrite an existing explicit cause with a later failure. Re-raising the same typed instance preserves its cause; a distinct wrapper may use one original exception as its explicit cause only before that wrapper has a cause. Every boundary appends initiating, read, recovery, synchronization, normalization, finalization, and close failures to `failures` before evidence finalization, binds the returned typed object, and bare-raises it so a finalizer-created cause is never displaced.
- A readable `FileNotFoundError` from any named-leaf proof means absence and contributes neither `identity=None` evidence nor a failure object unless a distinct held descriptor requires held evidence. Every other `OSError` produces current evidence with `identity=None` and keeps that exact exception in the ordered failure ledger; shared immutable named-leaf proofs and scan states carry the object until the typed boundary.

## Verified Repo Truths

- `w3xtool/description_cache_publication_fs.py:31-45` checks a directory identity and then separately calls `shutil.rmtree(name, dir_fd=...)`; that split is the uncloseable destructive check/use race this plan removes.
- The deletion callable currently reaches absent-output rollback, replacement commit, recovered-stage cleanup, and final-stage cleanup through `description_cache_publication_absent.py`, `description_cache_publication_commit.py`, `description_cache_publication_recovery.py`, `description_cache_publication_stage.py`, and `description_cache_publication_transaction.py`.
- `w3xtool/atomic_rename.py` already supplies fail-closed descriptor-relative no-replace and exchange primitives for macOS and Linux and raises `AtomicRenameUnavailableError` on unsupported hosts.
- `DescriptionCacheMigrationResult` currently contains only accepted/rejected counts, rejection rows, and the output path; `run_description_cache_cli()` currently prints only those counts and output.
- `tests/test_trusted_description_cache_anchored.py::test_anchored_loader_proves_the_same_bytes_as_public_loader` already locks public/descriptor loader parity and remains in the focused gate.
- No `CLAUDE.md` exists in the worktree; `/Users/zhongerbing/Documents/xm/war3_xg/w3xray/AGENTS.md` is the applicable checked-in repository guide.

---

## Pre-implementation documentation checkpoint

After the independent plan review reports zero Critical and zero Important findings, freeze
and commit the two documents before Task 1 writes any Python. Syntax parsing is insufficient:
first pipe every complete module fence (identified by its leading module docstring) through
Ruff's undefined-name and unused-import rules without writing production files:

````bash
python3 - <<'PY'
from pathlib import Path
import re
import subprocess

plan = Path(
    "docs/superpowers/plans/"
    "2026-07-16-retained-description-cache-generations.md"
)
text = plan.read_text(encoding="utf-8")
fences = re.findall(
    r"^```python\s*\n(.*?)^```\s*$",
    text,
    re.MULTILINE | re.DOTALL,
)
checked = 0
for index, code in enumerate(fences, start=1):
    if not code.lstrip().startswith('"""'):
        continue
    checked += 1
    completed = subprocess.run(
        (
            "uv",
            "run",
            "ruff",
            "check",
            "--select",
            "F401,F821",
            "--stdin-filename",
            f"complete_fence_{index}.py",
            "-",
        ),
        input=code,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
if checked == 0:
    raise SystemExit("no complete Python module fences found")
PY
````

Expected: exit `0`; every complete module fence is free of F401 and F821. Then commit:

```bash
git add \
  docs/superpowers/specs/2026-07-16-retained-description-cache-generations-design.md \
  docs/superpowers/plans/2026-07-16-retained-description-cache-generations.md
git commit -m "docs: plan retained cache generations"
```

Record that commit as the Task 1 base in the SDD ledger. Later Task 3 may amend and commit
the specification again, but the implementation plan itself must never remain untracked.

---

### Task 1: Immutable retained-generation model and atomic preservation primitive

**Files:**
- Create: `w3xtool/description_cache_publication_models.py`
- Create: `w3xtool/description_cache_publication_retention_names.py`
- Create: `w3xtool/description_cache_publication_named_leaf.py`
- Create: `w3xtool/description_cache_publication_retention.py`
- Create: `w3xtool/description_cache_publication_retention_installed.py`
- Create: `w3xtool/description_cache_publication_retention_recovery.py`
- Create: `tests/test_description_cache_publication_retention.py`
- Create: `tests/test_description_cache_retained_generations.py`
- Create: `tests/test_description_cache_publication_retention_collisions.py`
- Create: `tests/test_description_cache_publication_retention_durability.py`
- Create: `tests/test_description_cache_publication_retention_races.py`
- Create: `tests/test_description_cache_publication_recovery_durability.py`
- Create: `tests/test_description_cache_publication_stage_io.py`
- Create: `tests/test_description_cache_publication_descriptor_close.py`
- Create: `tests/test_description_cache_cli_retention.py`
- Modify: `w3xtool/description_cache_publication_errors.py`
- Modify: `tests/test_atomic_rename.py`

**Interfaces:**
- Produces: `RetainedCacheRole`, the closed values `PREVIOUS`, `FAILED_STAGE`, `FAILED_OUTPUT`, and `RECOVERY`.
- Produces: `RetainedCacheRecord(path, role, device, inode)` with an `identity` property; the record is valid for any no-follow filesystem object preserved during a race, not only directories.
- Produces: `PublicationTransientRecord(parent, leaf_name, parent_identity, identity, held_identity=None)`; `identity` is the current no-follow leaf when available and `held_identity` is the exact still-open captured stage directory when one was captured, so a post-capture leaf takeover cannot conflate the two objects.
- Produces: `DescriptionCachePublicationResult(active, retained=())`.
- Produces internal `RetainedCacheExpectation(record, verified)` and `DescriptionCachePublicationProof(result, retained_expectations=())`; the public result stays unchanged, while exact previous-generation digests survive until the final caller boundary.
- Produces internal `NamedLeafProof(readable, identity, failure)` and `RetainedEvidenceReproof(retained=(), transient=(), failures=())`; `FileNotFoundError` is readable absence with no failure, while every other `OSError` is unreadable `identity=None` evidence plus the exact failure object.
- Produces: pure `merge_retained(earlier, later)` and `merge_failures(earlier, later)` with stable first-occurrence/identity de-duplication.
- Extends: every `DescriptionCachePublicationError` with immutable `retained`, `transient`, and `failures` tuples so filesystem evidence and every independent original exception reach the caller without changing its typed subclass; stage-creation transient errors occur before nested lifecycle catches and propagate unchanged.
- Produces internal `RetainedObjectInstalledContextError(installed, detail, retained=(), transient=(), failures=())`; it proves the intended retained target was observed with the exact source identity and therefore marks the no-rollback side of the commit boundary even when subsequent fsync/binding/evidence proof is uncertain. Caller-visible `retained` still contains only live, publicly addressable records.
- Produces internal `installed_context_error(installed, evidence) -> RetainedObjectInstalledContextError`; every installed-target caller uses this one non-lossy wrapper so the finalized error object, its ordered ledger, and its existing cause remain reachable.
- Produces internal `read_named_leaf(parent_descriptor, name) -> NamedLeafProof` in the focused named-leaf module; raw retention, recovery, rollback selection, stage capture/location, and evidence reproof use it instead of catch-and-drop `OSError` helpers.
- Produces: `RetainedCacheNames(parent, transaction_id)` and `path(role)`.
- Produces: `retain_object(parent_descriptor, parent_identity, source, expected, names, role, rename_noreplace) -> RetainedCacheRecord`.
- Produces internal `move_object_to_recovery(parent_descriptor, parent_identity, source, expected, names, rename_noreplace) -> RetainedCacheRecord` in the recovery module; it alone owns recovery moves and their mandatory two-name postcondition proof, while the main retention module owns only intended-role state transitions.
- Produces internal `finish_installed_target(...) -> RetainedCacheRecord` in the installed-target module; it owns source-name reacquisition after the intended target is exact, keeping the main intended-role state machine below 200 pure LOC.
- Consumes without changing: `DirectoryIdentity`, `directory_identity()`, and `object_identity()` from `description_cache_publication_fs.py`; Task 2 removes the legacy remover only after every caller has migrated.

- [ ] **Step 1: Write the complete pre-implementation behavioral RED suite**

Before editing any production module, create the complete Task 2 behavioral suite in the focused files listed below. `test_description_cache_retained_generations.py` owns ordinary success/rollback outcomes; `test_description_cache_publication_retention_collisions.py` owns retained-name collisions; `test_description_cache_publication_retention_races.py` owns namespace takeovers and parent-binding races; `test_description_cache_publication_retention_durability.py` owns post-retain fsync/revalidation failures; `test_description_cache_publication_recovery_durability.py` owns every reverse-exchange failure boundary; `test_description_cache_publication_stage_io.py` owns writer-proof and held-stage replacement races; `test_description_cache_publication_descriptor_close.py` owns successful and failing transaction descriptor-close faults; and `test_description_cache_cli_retention.py` owns success and failure CLI evidence. Use only currently importable public modules, local glob helpers, and string role values in this first RED form; do not import a proposed module or symbol merely to fail collection.

The initial files must already include every unsupported-host, intended-role collision, recovery collision, success CLI, failure CLI, capture-normalization, post-retain durability, parent takeover, and stage-leaf takeover case specified later in Task 2. They must also include: source-name reacquisition after raw retention success and error; an atomic recovery move that really completes before its injected callable raises; a normal-return recovery move followed immediately by a foreign object reacquiring the source name, which must surface both the exact recovery record and the current source transient; an absent-output no-replace move that really completes before its injected callable raises and must preserve the resulting `PublicationCommitContextError` subtype after successful `failed-output` retention; an unexpected backup leaf in absent-output success and in a simultaneous stage-finalization failure; writer-return leaf replacement; whole-stage self-consistent replacement after held-stage validation but before the first rename; active and retained byte mutation immediately before the public result boundary; same-inode/same-size mutation of an early active leaf while a later retained generation is read; retained-leaf replacement between the first and second boundary reproof; replacement of the public parent during the final leaf reproof; late insertion of stage, backup, and both names during result revalidation; `ValueError` and `RuntimeError` injected separately from stage creation, build, validation, absent-output post-install proof, backup finalization, and stage finalization, with both private names still attempted and the exact injected exception reachable through `failures`, `__cause__`, or `__context__`; parent loss at both result and error boundaries with the descriptor-proved active leaf reported as transient; recovery failure immediately after reverse exchange and at every subsequent proof, rename, validation, retain, and fsync boundary; a candidate already at the exact `recovery` leaf without a prior record; a foreign exact recovery candidate with the recovery target free; permission/I/O failures while re-proving named retained and transient leaves with `identity=None`; and a shared assertion that every surfaced retained record still passes `path.stat(follow_symlinks=False)`. These are RED requirements now, not tests to be added after their production modules exist. Complete import-cycle smoke coverage is intentionally added only after all proposed production modules exist, so the initial RED command never fails collection on a proposed module.

All hostile stage-leaf takeover REDs begin only after `create_stage_and_capture()` has
successfully returned the held descriptor and captured identity. Do not add a zero-write or
byte-for-byte assertion for a replacement injected between the real `mkdirat` return and the
first stage open/identity capture: that is the explicit POSIX provenance precondition, not a
race this plan can close with another named proof.

The same initial suite injects `FileExistsError` after the primary intended-role move has
really completed and separately exercises a true intended-role collision. The first case
must surface the installed-target subtype and forbid rollback; the second must retain the
exact source as `recovery` while reporting the occupied intended target with its current
identity. A normal-return target takeover must report the simultaneously observed source
side rather than discarding it. Add post-`mkdir` `FileExistsError` cases from stage open and
initial parent sync; both normalize the created inode instead of becoming mkdir collisions.
Add a rollback-source selection failure seeded with prior transient evidence and require
every prior name to be freshly re-proved at the caller boundary. For each ordinary
private-attempt exception, require evidence for the failed private leaf as well as proof
that the other leaf was attempted. Finally, remove or move both the stage leaf and active
output while the stage descriptor remains open; finalization must report the held stage
identity unless it can re-prove that identity at a legal retained name.

Every focused failure test uses one identity-only assertion; equality of exception text is
deliberately insufficient:

```python
def assert_failure_order(
    error: DescriptionCachePublicationError,
    expected: tuple[Exception, ...],
) -> None:
    assert len(error.failures) == len(expected)
    assert all(
        actual is wanted
        for actual, wanted in zip(error.failures, expected, strict=True)
    )
```

The initial RED suite includes the following exact two-fault/multi-fault cases before any
production edit:

- `test_installed_target_reacquisition_keeps_move_fault_after_recovery_success` makes the
  intended move complete, reacquires the source, then raises the exact `move_fault`; recovery
  succeeds and the installed-target error ledger is exactly `(move_fault,)`.
- `test_installed_target_reacquisition_keeps_move_and_recovery_faults` repeats that sequence
  but rejects the source-to-recovery move with `recovery_fault`; the ledger is exactly
  `(move_fault, recovery_fault)`, the wrapper cause is the recovery typed error, and that
  error's existing cause still reaches `recovery_fault`.
- Four stage-creation tests pair the exact initiating creation/build fault with, respectively,
  parent-proof loss, named-stage read failure, retention failure, and final evidence parent
  failure. Each ledger begins with the initiating object and then the later exact objects in
  operation order; none changes the finalizer-returned cause.
- Four stage-location tests inject exact parent-proof, stage-read, foreign-retention, and
  failed-stage-retention objects. Each reaches the final locator error after its already-known
  failures, and the typed-error pass-through case remains byte-for-byte unchanged.
- One shared finalizer regression parameterizes durable-retention sync, recovery-state sync,
  stage collision/creation evidence, and backup evidence. It injects `primary_fault`, then
  `secondary_fault`, then a terminal parent-proof `finalizer_fault`; the final ledger contains
  those exact objects in that order and the finalizer error's cause is not replaced.
- `test_parent_bound_retained_install_keeps_finalized_error` installs the exact retained
  object, fails the first parent check, then makes final evidence reproof fail. The surfaced
  installed subtype contains the exact finalized typed object after its prior failures and
  preserves that object's cause.
- `test_parent_bound_validation_and_parent_proof_keep_both_faults` makes the validator raise
  exact `validation_fault`, then makes the public-parent recheck raise a typed parent error
  whose exact cause is `parent_fault`. The surfaced object is that same parent error, its
  ledger is exactly `(validation_fault, parent_fault)`, and its existing cause remains
  `parent_fault`; no `raise ... from validation_fault` replacement is permitted.
- Four low-level wrapper REDs inject distinct exact `OSError` objects into initial
  publication-parent `open`, parent-descriptor `fstat`, public-parent no-follow `stat`, and
  stage-writer leaf `open`. Each direct or later-finalized typed error begins with exactly
  that object in `failures`, preserves its identity/order, and may also expose the same
  object as `__cause__`; cause reachability never substitutes for ledger membership.
- Two end-to-end REDs invoke `create_stage_and_capture()` itself. One faults the initial
  parent-descriptor `fstat` while `parent_identity` is still unavailable; the other faults
  the initial public-parent no-follow `stat` while `created` is still false. Each surfaced
  typed error has the exact injected low-level object as `failures[0]` by identity, contains
  it only once, and preserves its existing cause; an aggregate publication wrapper is never
  substituted for that first ledger event.
- Recovery normalization tests pair the exact original rollback fault with each retention,
  sync, evidence, and parent-binding normalization fault. The original fault and its existing
  ledger precede the normalization fault, and no catch adds a new `from` clause.
- A named-read matrix faults raw source, raw target, rollback candidate, recovery candidate,
  retained-row reproof, transient-row reproof, stage capture, and both locator scan rounds.
  Every non-`FileNotFoundError` case asserts one current `identity=None` record and the exact
  `OSError`; matching `FileNotFoundError` cases assert readable absence, no phantom record,
  and no failure-ledger entry.

Also create `tests/test_description_cache_publication_retention.py` with real directories and the production no-replace adapter. For the first RED only, import the already-existing filesystem module as `retention` and access the proposed contracts through that module inside each test body. This deliberately fails at runtime because the behavior is absent, rather than failing collection because a new module cannot be imported:

```python
"""Atomic non-destructive retention of trusted-cache generations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import rename_in_parent
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool import description_cache_publication_fs as retention


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _open_parent(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )


def test_retain_object_moves_the_exact_inode_without_overwrite(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-backup-a"
    source.mkdir()
    expected = _identity(source)
    names = retention.RetainedCacheNames(tmp_path, "1" * 32)
    descriptor = _open_parent(tmp_path)
    try:
        retained = retention.retain_object(
            descriptor,
            _identity(tmp_path),
            source,
            expected,
            names,
            retention.RetainedCacheRole.PREVIOUS,
            rename_in_parent,
        )
    finally:
        os.close(descriptor)

    assert retained.role is retention.RetainedCacheRole.PREVIOUS
    assert retained.identity == expected
    assert retained.path == names.path(retention.RetainedCacheRole.PREVIOUS)
    assert _identity(retained.path) == expected
    assert not source.exists()


def test_source_swap_immediately_before_retention_preserves_both_directories(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-backup-b"
    source.mkdir()
    expected = _identity(source)
    displaced = tmp_path / "displaced-expected"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    foreign_identity = _identity(foreign)
    names = retention.RetainedCacheNames(tmp_path, "2" * 32)

    def swap_then_rename(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        os.rename(
            source_name,
            displaced.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        os.rename(
            foreign.name,
            source_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        rename_in_parent(parent_descriptor, source_name, destination_name)

    descriptor = _open_parent(tmp_path)
    try:
        with pytest.raises(
            PublicationCommitContextError,
            match="NEEDS_CONTEXT",
        ) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                retention.RetainedCacheRole.PREVIOUS,
                swap_then_rename,
            )
    finally:
        os.close(descriptor)

    assert _identity(displaced) == expected
    assert _identity(names.path(retention.RetainedCacheRole.RECOVERY)) == foreign_identity
    assert not names.path(retention.RetainedCacheRole.PREVIOUS).exists()
    assert len(raised.value.retained) == 1
    assert raised.value.retained[0].role is retention.RetainedCacheRole.RECOVERY
    assert raised.value.retained[0].identity == foreign_identity


def test_retain_object_never_overwrites_an_existing_retained_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-stage-c"
    source.mkdir()
    expected = _identity(source)
    names = retention.RetainedCacheNames(tmp_path, "3" * 32)
    collision = names.path(retention.RetainedCacheRole.FAILED_STAGE)
    collision.mkdir()
    collision_identity = _identity(collision)
    descriptor = _open_parent(tmp_path)
    try:
        with pytest.raises(
            PublicationCommitContextError,
            match="NEEDS_CONTEXT",
        ) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                retention.RetainedCacheRole.FAILED_STAGE,
                rename_in_parent,
            )
    finally:
        os.close(descriptor)

    recovery = names.path(retention.RetainedCacheRole.RECOVERY)
    assert not source.exists()
    assert _identity(collision) == collision_identity
    assert _identity(recovery) == expected
    assert raised.value.retained[0].path == recovery
    assert raised.value.retained[0].identity == expected


def test_unmoved_exact_source_does_not_create_an_absent_target_transient(
    tmp_path: Path,
) -> None:
    source = tmp_path / ".w3xray-description-cache-stage-d"
    source.mkdir()
    expected = _identity(source)
    names = retention.RetainedCacheNames(tmp_path, "4" * 32)

    def return_without_moving(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> None:
        return

    descriptor = _open_parent(tmp_path)
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            retention.retain_object(
                descriptor,
                _identity(tmp_path),
                source,
                expected,
                names,
                retention.RetainedCacheRole.FAILED_STAGE,
                return_without_moving,
            )
    finally:
        os.close(descriptor)

    assert tuple(
        (record.path, record.identity) for record in raised.value.transient
    ) == ((source, expected),)
    assert not names.path(retention.RetainedCacheRole.FAILED_STAGE).exists()


def test_already_recovery_candidate_that_disappeared_has_no_phantom_transient(
    tmp_path: Path,
) -> None:
    names = retention.RetainedCacheNames(tmp_path, "5" * 32)
    recovery = names.path(retention.RetainedCacheRole.RECOVERY)
    recovery.mkdir()
    expected = _identity(recovery)
    displaced = tmp_path / "displaced-recovery"
    recovery.rename(displaced)
    descriptor = _open_parent(tmp_path)
    try:
        with pytest.raises(PublicationCommitContextError) as raised:
            retention.move_object_to_recovery(
                descriptor,
                _identity(tmp_path),
                recovery,
                expected,
                names,
                rename_in_parent,
            )
    finally:
        os.close(descriptor)

    assert raised.value.retained == ()
    assert raised.value.transient == ()
    assert _identity(displaced) == expected
```

Add `test_source_swap_records_non_directory_recovery_without_following`, parameterized over two typed factory callables (one creates a regular file; one creates a symlink to a deliberately absent target), beside the directory swap test. This avoids a variant-discriminating `if` in the test. It uses the same real descriptor-relative swap/no-replace adapter: capture and displace the source directory, install the factory's object at the source name, then let the rename proceed. Require typed `NEEDS_CONTEXT`, the decoy's no-follow inode under the same transaction's `recovery` name, an exact generic record, and the original directory at its displaced name. The symlink factory returns its expected link text so the assertion can use `os.readlink(recovery)` and prove the target remains absent without branching or following it. No mock may replace the filesystem namespace operations. Both variants belong to the initial behavioral RED command and final GREEN/static gates.

- [ ] **Step 2: Run one explicit RED gate and prove failures are behavioral**

Run:

```bash
uv run python -m pytest -q \
  tests/test_description_cache_publication_retention.py \
  tests/test_description_cache_retained_generations.py \
  tests/test_description_cache_publication_retention_collisions.py \
  tests/test_description_cache_publication_retention_durability.py \
  tests/test_description_cache_publication_retention_races.py \
  tests/test_description_cache_publication_recovery_durability.py \
  tests/test_description_cache_publication_stage_io.py \
  tests/test_description_cache_publication_descriptor_close.py \
  tests/test_description_cache_cli_retention.py
```

Expected: collection succeeds, then tests fail at their `When` or observable `Then`: the primitive contract is absent at runtime, replacement/rollback deletes evidence, unsupported-host preflight creates state too late, collisions cannot fall back safely, and CLI output omits retained records. Any import/collection failure is a test defect and must be fixed before production code is touched.

- [ ] **Step 3: Add the closed immutable model and exact retained-name builder**

Create `w3xtool/description_cache_publication_models.py`:

```python
"""Immutable outcomes for retained trusted-cache publication."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path

from .trusted_description_cache_models import VerifiedDescriptionCache


@unique
class RetainedCacheRole(StrEnum):
    """The only evidence roles publication may assign."""

    PREVIOUS = "previous"
    FAILED_STAGE = "failed-stage"
    FAILED_OUTPUT = "failed-output"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class RetainedCacheRecord:
    """One intentionally preserved sibling object and its proven inode."""

    path: Path
    role: RetainedCacheRole
    device: int
    inode: int

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode


@dataclass(frozen=True, slots=True)
class PublicationTransientRecord:
    """One non-normalized leaf anchored to the parent that created it."""

    parent: Path
    leaf_name: str
    parent_identity: tuple[int, int]
    identity: tuple[int, int] | None
    held_identity: tuple[int, int] | None = None

    @property
    def path(self) -> Path:
        return self.parent / self.leaf_name


@dataclass(frozen=True, slots=True)
class DescriptionCachePublicationResult:
    """The verified active cache plus non-active evidence."""

    active: VerifiedDescriptionCache
    retained: tuple[RetainedCacheRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class RetainedCacheExpectation:
    """Exact validated bytes expected at one successful retained record."""

    record: RetainedCacheRecord
    verified: VerifiedDescriptionCache


@dataclass(frozen=True, slots=True)
class DescriptionCachePublicationProof:
    """Internal success proof kept until the public result boundary."""

    result: DescriptionCachePublicationResult
    retained_expectations: tuple[RetainedCacheExpectation, ...] = ()


@dataclass(frozen=True, slots=True)
class NamedLeafProof:
    """One no-follow named read and its exact non-absence failure."""

    readable: bool
    identity: tuple[int, int] | None
    failure: OSError | None = None

    @property
    def failures(self) -> tuple[Exception, ...]:
        return () if self.failure is None else (self.failure,)


@dataclass(frozen=True, slots=True)
class RetainedEvidenceReproof:
    """Current exact records, uncertain names, and exact read failures."""

    retained: tuple[RetainedCacheRecord, ...] = ()
    transient: tuple[PublicationTransientRecord, ...] = ()
    failures: tuple[Exception, ...] = ()


__all__ = (
    "DescriptionCachePublicationProof",
    "DescriptionCachePublicationResult",
    "NamedLeafProof",
    "PublicationTransientRecord",
    "RetainedCacheExpectation",
    "RetainedEvidenceReproof",
    "RetainedCacheRecord",
    "RetainedCacheRole",
)
```

After the model module exists but before editing `description_cache_publication_errors.py`, add three `merge_retained` unit cases to the primitive test file: completely disjoint groups must remain `(earlier..., later...)`; partially overlapping groups must keep the first occurrence in transaction order; and fully repeated groups must collapse to one copy. Add the same three shapes for `merge_failures`, but compare exception object identity and include two distinct exception instances with equal text to prove they are not collapsed. Import the existing errors module as a namespace and call the missing helpers inside the test body, then run all six cases and require runtime RED rather than collection failure.

In `w3xtool/description_cache_publication_errors.py`, retain existing subclasses and add failure evidence to the base constructor. Exceptions remain deliberately mutable because Python attaches traceback state. One pure `merge_retained(earlier, later)` function preserves transaction order and removes duplicates; `replace_retained()`, `replace_transient()`, `replace_failures()`, and the close-context appender are the only evidence mutation points on a propagating error:

```python
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
)


def merge_retained(
    earlier: tuple[RetainedCacheRecord, ...],
    later: tuple[RetainedCacheRecord, ...],
) -> tuple[RetainedCacheRecord, ...]:
    """Merge evidence in event order while keeping the first occurrence."""
    return tuple(dict.fromkeys((*earlier, *later)))


def merge_failures(
    earlier: tuple[Exception, ...],
    later: tuple[Exception, ...],
) -> tuple[Exception, ...]:
    """Merge exception evidence by identity in event order."""
    merged: list[Exception] = []
    for failure in (*earlier, *later):
        if all(current is not failure for current in merged):
            merged.append(failure)
    return tuple(merged)


class DescriptionCachePublicationError(OSError):
    """A trusted cache could not be published without partial evidence."""

    __slots__: tuple[str, ...] = ("detail", "failures", "retained", "transient")

    detail: str
    retained: tuple[RetainedCacheRecord, ...]
    transient: tuple[PublicationTransientRecord, ...]
    failures: tuple[Exception, ...]

    def __init__(
        self,
        detail: str,
        retained: tuple[RetainedCacheRecord, ...] = (),
        transient: tuple[PublicationTransientRecord, ...] = (),
        failures: tuple[Exception, ...] = (),
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retained = retained
        self.transient = transient
        self.failures = failures

    def replace_retained(
        self,
        retained: tuple[RetainedCacheRecord, ...],
    ) -> None:
        self.retained = retained

    def replace_transient(
        self,
        transient: tuple[PublicationTransientRecord, ...],
    ) -> None:
        self.transient = transient

    def replace_failures(self, failures: tuple[Exception, ...]) -> None:
        self.failures = failures

    def append_close_context(
        self,
        detail: str,
        failures: tuple[Exception, ...],
    ) -> None:
        """Append descriptor-close evidence without replacing this subtype."""
        self.detail = f"{self.detail}; {detail}; NEEDS_CONTEXT"
        self.failures = merge_failures(self.failures, failures)

    @override
    def __str__(self) -> str:
        return self.detail
```

Add `merge_retained` and `merge_failures` to the error module's `__all__`; keep every existing typed subclass exported. `failures` is not display text and does not change `__str__`; it is the typed non-lossy ledger used when a boundary must preserve two independent exceptions without replacing an existing `__cause__`.

Add this internal typed commit-boundary error beside the existing subclasses and export it
for lifecycle modules only:

```python
class RetainedObjectInstalledContextError(PublicationCommitContextError):
    """The intended retained target was installed; rollback is forbidden."""

    __slots__: tuple[str, ...] = ("installed",)

    installed: RetainedCacheRecord

    def __init__(
        self,
        installed: RetainedCacheRecord,
        detail: str,
        retained: tuple[RetainedCacheRecord, ...] = (),
        transient: tuple[PublicationTransientRecord, ...] = (),
        failures: tuple[Exception, ...] = (),
    ) -> None:
        super().__init__(detail, retained, transient, failures)
        self.installed = installed


def installed_context_error(
    installed: RetainedCacheRecord,
    evidence: DescriptionCachePublicationError,
) -> RetainedObjectInstalledContextError:
    """Wrap finalized evidence without discarding that object or its cause."""
    return RetainedObjectInstalledContextError(
        installed,
        str(evidence),
        evidence.retained,
        evidence.transient,
        merge_failures(evidence.failures, (evidence,)),
    )
```

Add `installed_context_error`, `merge_retained`, and `merge_failures` to the error module's
`__all__`; keep every existing typed subclass exported. `installed` is an internal transaction fact and may name a path below a parent whose public
binding was later lost; it is never printed directly. Evidence finalization separately
rebuilds `retained`/`transient`. Raw retention raises this subtype whenever the intended
role was observed exact after the atomic move, and the durable adapter preserves the subtype
through every later failure.

Create the name contract in the dedicated `w3xtool/description_cache_publication_retention_names.py`; the move primitive imports this model and does not also own naming validation:

```python
"""Validated retained-generation names for one publication transaction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .description_cache_publication_errors import DescriptionCachePublicationError
from .description_cache_publication_models import RetainedCacheRole


_RETAINED_PREFIX: Final = ".w3xray-description-cache-retained-"
_HEX: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class RetainedCacheNames:
    parent: Path
    transaction_id: str

    def __post_init__(self) -> None:
        if len(self.transaction_id) != 32 or any(
            character not in _HEX for character in self.transaction_id
        ):
            raise DescriptionCachePublicationError(
                "transaction identifier must be 32 lowercase hex digits"
            )

    def path(self, role: RetainedCacheRole) -> Path:
        return self.parent / f"{_RETAINED_PREFIX}{self.transaction_id}-{role.value}"


__all__ = ("RetainedCacheNames",)
```

Create the shared no-follow proof in
`w3xtool/description_cache_publication_named_leaf.py`. This is the only helper that
classifies named-read exceptions: readable `FileNotFoundError` is absence, while every other
`OSError` remains attached to the immutable proof by identity.

```python
"""Exact no-follow proofs for publication-parent leaves."""

from __future__ import annotations

from .description_cache_publication_fs import object_identity
from .description_cache_publication_models import NamedLeafProof


def read_named_leaf(parent_descriptor: int, name: str) -> NamedLeafProof:
    """Read one name without treating non-absence I/O failure as absence."""
    try:
        return NamedLeafProof(
            True,
            object_identity(parent_descriptor, name),
        )
    except FileNotFoundError:
        return NamedLeafProof(True, None)
    except OSError as exc:
        return NamedLeafProof(False, None, exc)


__all__ = ("read_named_leaf",)
```

After the model, names, and primitive modules exist, refactor `tests/test_description_cache_publication_retention.py` to import `RetainedCacheRole` from the model module, `RetainedCacheNames` from the names module, and the primitive module namespace separately. Re-run that test and require the next RED to be the missing `retain_object` behavior, then implement Step 4. This import-only refactor must not change assertions. Task 2 adds a dedicated clean-interpreter smoke gate after every proposed production module exists; a six-module in-process subset is not sufficient to prove the complete split graph remains acyclic.

- [ ] **Step 4: Implement atomic no-replace retention with post-move identity proof**

In `description_cache_publication_retention.py`, define only the intended-role state machine,
its named-object proof, and its transient conversion. Put the recovery move and mandatory
two-name recovery proof in
`description_cache_publication_retention_recovery.py`; the main state machine calls the
exported internal `move_object_to_recovery()` contract. Put the commit-crossing intended
target/source-reacquisition outcome in
`description_cache_publication_retention_installed.py`; the main state machine calls
`finish_installed_target()` after proving the target exact. `merge_retained()` relies on
frozen/hashable records so `dict.fromkeys()` preserves first-seen transaction order while
removing duplicate evidence accumulated by nested recovery. An occupied intended role never
causes overwrite: if the source inode is still exact and `recovery` is free, atomically move
the source to `recovery` and raise typed `NEEDS_CONTEXT` carrying that record. An unexpected
object that crossed a move is likewise moved from the intended role to `recovery` when
possible. If `recovery` is also occupied or no-replace is rejected, preserve every current
name and return typed `NEEDS_CONTEXT`; an unmoved unexpected object at an intended retained
leaf is never mislabeled as `previous`/`failed-*`. No object is deleted. Neither primitive
fsyncs: Task 2's mandatory durability wrapper fsyncs the held parent after every return and
every error, including the “moved to recovery and raised” outcome; lifecycle code may never
call any raw retention submodule directly.

```python
"""Atomic no-replace movement of one non-active cache object."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_models import (
    NamedLeafProof,
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_retention_installed import (
    finish_installed_target,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_retention_recovery import (
    move_object_to_recovery,
)


type Rename = Callable[[int, str, str], None]


def retain_object(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    expected: DirectoryIdentity,
    names: RetainedCacheNames,
    role: RetainedCacheRole,
    rename_noreplace: Rename,
) -> RetainedCacheRecord:
    if source.parent != names.parent:
        raise PublicationCommitContextError(
            "retention escaped the publication parent; NEEDS_CONTEXT"
        )
    target = names.path(role)
    source_before = read_named_leaf(parent_descriptor, source.name)
    if not source_before.readable or source_before.identity is None:
        context_error = PublicationCommitContextError(
            "retention source cannot be proved; NEEDS_CONTEXT",
            transient=_proof_transient(
                parent_identity,
                source,
                source_before,
                None,
            ),
            failures=source_before.failures,
        )
        if source_before.failure is not None:
            raise context_error from source_before.failure
        raise context_error
    if source_before.identity != expected:
        recovery = move_object_to_recovery(
            parent_descriptor,
            parent_identity,
            source,
            source_before.identity,
            names,
            rename_noreplace,
        )
        raise PublicationCommitContextError(
            "retention source identity changed and was preserved as recovery; "
            "NEEDS_CONTEXT",
            (recovery,),
        )

    move_error: Exception | None = None
    try:
        rename_noreplace(parent_descriptor, source.name, target.name)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - atomic move reproof
        move_error = exc

    source_after = read_named_leaf(parent_descriptor, source.name)
    target_after = read_named_leaf(parent_descriptor, target.name)
    prior_failures = merge_failures(
        () if move_error is None else (move_error,),
        (*source_after.failures, *target_after.failures),
    )
    if target_after.identity == expected:
        return finish_installed_target(
            parent_descriptor,
            parent_identity,
            source,
            source_after.readable,
            source_after.identity,
            target,
            expected,
            role,
            names,
            rename_noreplace,
            move_error,
            prior_failures,
        )
    if (
        source_after.identity == expected
        and target_after.readable
        and target_after.identity is not None
    ):
        collision = _proof_transient(
            parent_identity,
            target,
            target_after,
            expected,
        )
        try:
            recovery = move_object_to_recovery(
                parent_descriptor,
                parent_identity,
                source,
                expected,
                names,
                rename_noreplace,
            )
        except PublicationCommitContextError as recovery_error:
            recovery_error.replace_transient(
                (*recovery_error.transient, *collision)
            )
            recovery_error.replace_failures(
                merge_failures(prior_failures, recovery_error.failures)
            )
            raise
        context_error = PublicationCommitContextError(
            "retained role was occupied; source preserved as recovery; NEEDS_CONTEXT",
            (recovery,),
            collision,
            prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    if target_after.readable and target_after.identity is not None:
        source_transient = _proof_transient(
            parent_identity,
            source,
            source_after,
            None,
        )
        try:
            recovery = move_object_to_recovery(
                parent_descriptor,
                parent_identity,
                target,
                target_after.identity,
                names,
                rename_noreplace,
            )
        except PublicationCommitContextError as recovery_error:
            recovery_error.replace_transient(
                (*recovery_error.transient, *source_transient)
            )
            recovery_error.replace_failures(
                merge_failures(prior_failures, recovery_error.failures)
            )
            raise
        context_error = PublicationCommitContextError(
            "retention moved an unexpected identity; NEEDS_CONTEXT",
            (recovery,),
            source_transient,
            prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    context_error = PublicationCommitContextError(
        "retention move could not be proved; NEEDS_CONTEXT",
        transient=(
            *_proof_transient(
                parent_identity,
                source,
                source_after,
                None,
            ),
            *_proof_transient(
                parent_identity,
                target,
                target_after,
                None,
            ),
        ),
        failures=prior_failures,
    )
    if move_error is not None:
        raise context_error from move_error
    raise context_error


def _proof_transient(
    parent_identity: DirectoryIdentity,
    path: Path,
    proof: NamedLeafProof,
    allowed: DirectoryIdentity | None,
) -> tuple[PublicationTransientRecord, ...]:
    if proof.readable and proof.identity == allowed:
        return ()
    return (
        PublicationTransientRecord(
            path.parent,
            path.name,
            parent_identity,
            proof.identity,
        ),
    )


__all__ = ("retain_object",)
```

Create `w3xtool/description_cache_publication_retention_installed.py` for the
commit-crossing intended-target outcome. It receives only the already-read source-side
proof, handles source-name reacquisition, and preserves the installed-target subtype:

```python
"""Postcondition handling after an intended retained target is exact."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_retention_recovery import (
    move_object_to_recovery,
)


type Rename = Callable[[int, str, str], None]


def finish_installed_target(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    source_readable: bool,
    source_identity: DirectoryIdentity | None,
    target: Path,
    expected: DirectoryIdentity,
    role: RetainedCacheRole,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    move_error: Exception | None,
    prior_failures: tuple[Exception, ...],
) -> RetainedCacheRecord:
    """Return only a clean intended target or raise the no-rollback subtype."""
    intended = RetainedCacheRecord(target, role, *expected)
    source_transient = _source_transient(
        parent_identity,
        source,
        source_readable,
        source_identity,
    )
    if source_readable and source_identity is not None:
        try:
            recovery = move_object_to_recovery(
                parent_descriptor,
                parent_identity,
                source,
                source_identity,
                names,
                rename_noreplace,
            )
        except PublicationCommitContextError as recovery_error:
            installed_error = RetainedObjectInstalledContextError(
                intended,
                str(recovery_error),
                merge_retained((intended,), recovery_error.retained),
                (*source_transient, *recovery_error.transient),
                merge_failures(
                    prior_failures,
                    recovery_error.failures,
                ),
            )
            raise installed_error from recovery_error
        context_error = RetainedObjectInstalledContextError(
            intended,
            "retention source name was reacquired; NEEDS_CONTEXT",
            (intended, recovery),
            failures=prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    if move_error is not None or source_transient:
        context_error = RetainedObjectInstalledContextError(
            intended,
            "retention target was installed but move completion is uncertain; "
            "NEEDS_CONTEXT",
            (intended,),
            source_transient,
            prior_failures,
        )
        if move_error is not None:
            raise context_error from move_error
        raise context_error
    return intended


def _source_transient(
    parent_identity: DirectoryIdentity,
    source: Path,
    readable: bool,
    identity: DirectoryIdentity | None,
) -> tuple[PublicationTransientRecord, ...]:
    if readable and identity is None:
        return ()
    return (
        PublicationTransientRecord(
            source.parent,
            source.name,
            parent_identity,
            identity,
        ),
    )


__all__ = ("finish_installed_target",)
```

On the double-failure branch, `prior_failures` already contains the exact intended-move
fault and `recovery_error.failures` already contains the exact recovery fault. The aggregate
typed `recovery_error` stays reachable as `installed_error.__cause__`; it is deliberately
not appended as a third ledger entry. The exact RED therefore remains
`(move_fault, recovery_fault)` with length two.

Create `w3xtool/description_cache_publication_retention_recovery.py` for the recovery move
and its complete two-name proof. The intended-role state machine above imports only this
function; it does not duplicate recovery proof state. This keeps both modules below the
250-pure-LOC ceiling while preserving the rule that a callable return or exception has no
completion meaning until both names are re-read:

```python
"""Recovery-role moves and two-name postcondition proof."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_models import (
    NamedLeafProof,
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_retention_names import RetainedCacheNames


type Rename = Callable[[int, str, str], None]


def move_object_to_recovery(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    expected: DirectoryIdentity,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
) -> RetainedCacheRecord:
    """Move one exact object to recovery and prove both namespace sides."""
    recovery = names.path(RetainedCacheRole.RECOVERY)
    if source == recovery:
        current = read_named_leaf(parent_descriptor, recovery.name)
        if current.readable and current.identity == expected:
            return RetainedCacheRecord(
                recovery,
                RetainedCacheRole.RECOVERY,
                *expected,
            )
        context_error = PublicationCommitContextError(
            "existing recovery object cannot be proved; NEEDS_CONTEXT",
            transient=_named_transient(
                parent_identity,
                recovery,
                current,
                None,
            ),
            failures=current.failures,
        )
        if current.failure is not None:
            raise context_error from current.failure
        raise context_error
    source_before = read_named_leaf(parent_descriptor, source.name)
    if source_before.identity != expected:
        proof = _reprove_recovery_move(
            parent_descriptor,
            parent_identity,
            source,
            recovery,
            expected,
        )
        context_error = PublicationCommitContextError(
            "unexpected retained object changed again; NEEDS_CONTEXT",
            proof.retained,
            proof.transient,
            merge_failures(source_before.failures, proof.failures),
        )
        if source_before.failure is not None:
            raise context_error from source_before.failure
        raise context_error
    move_error: Exception | None = None
    try:
        rename_noreplace(parent_descriptor, source.name, recovery.name)
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - recovery move reproof
        move_error = exc
    proof = _reprove_recovery_move(
        parent_descriptor,
        parent_identity,
        source,
        recovery,
        expected,
    )
    failures = merge_failures(
        () if move_error is None else (move_error,),
        proof.failures,
    )
    if (
        move_error is None
        and proof.complete
        and proof.retained
        and not proof.transient
    ):
        return proof.retained[0]
    detail = (
        "recovery move completed but its callable raised; NEEDS_CONTEXT"
        if move_error is not None and proof.complete
        else "unexpected retained object needs recovery context; NEEDS_CONTEXT"
    )
    context_error = PublicationCommitContextError(
        detail,
        proof.retained,
        proof.transient,
        failures,
    )
    if move_error is not None:
        raise context_error from move_error
    raise context_error


@dataclass(frozen=True, slots=True)
class _RecoveryMoveProof:
    complete: bool
    retained: tuple[RetainedCacheRecord, ...]
    transient: tuple[PublicationTransientRecord, ...]
    failures: tuple[Exception, ...]


def _reprove_recovery_move(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    source: Path,
    recovery: Path,
    expected: DirectoryIdentity,
) -> _RecoveryMoveProof:
    source_proof = read_named_leaf(parent_descriptor, source.name)
    recovery_proof = read_named_leaf(parent_descriptor, recovery.name)
    retained = (
        (
            RetainedCacheRecord(
                recovery,
                RetainedCacheRole.RECOVERY,
                *expected,
            ),
        )
        if recovery_proof.identity == expected
        else ()
    )
    transient = tuple(
        PublicationTransientRecord(
            source.parent,
            path.name,
            parent_identity,
            proof.identity,
        )
        for path, proof, allowed in (
            (source, source_proof, None),
            (recovery, recovery_proof, expected),
        )
        if not proof.readable
        or (proof.identity is not None and proof.identity != allowed)
    )
    return _RecoveryMoveProof(
        bool(
            retained
            and source_proof.readable
            and source_proof.identity is None
        ),
        retained,
        transient,
        merge_failures(source_proof.failures, recovery_proof.failures),
    )


def _named_transient(
    parent_identity: DirectoryIdentity,
    path: Path,
    proof: NamedLeafProof,
    allowed: DirectoryIdentity | None,
) -> tuple[PublicationTransientRecord, ...]:
    if proof.readable and proof.identity == allowed:
        return ()
    return (
        PublicationTransientRecord(
            path.parent,
            path.name,
            parent_identity,
            proof.identity,
        ),
    )


__all__ = ("move_object_to_recovery",)
```

Use `read_named_leaf()` before the move and one `NamedLeafProof` for each side after every
return or exception so a concurrently substituted non-directory is preserved rather than
traversed. `FileExistsError` has no special completion meaning. If the intended target has
the expected identity, the installed-target boundary wins; if the exact source remains and
the target is occupied, the source moves to `recovery` and the occupied target remains
transient evidence. A foreign but exact current source is moved to the free `recovery` role
before typed failure; it is not left at a stage/backup transient merely because it differs
from the caller's earlier identity. The success result is emitted only when the destination
has the expected no-follow identity and a readable source proof is exactly absent. A foreign
or unreadable source after a normal-return recovery move forces typed `NEEDS_CONTEXT` carrying
the exact recovery record plus current source evidence; `proof.complete` may never hide a
non-empty transient tuple. In terminal failure branches, a readable absent intended target
and a readable absent source-equals-recovery candidate are allowed absence and emit no
held-less `identity=None` phantom; unreadable or foreign leaves remain explicit. Once that intended target
is observed exact, every later error is `RetainedObjectInstalledContextError`, so callers
cannot mistake a crossed commit boundary for a rollback-eligible collision. Callers that
require a cache directory already supply an identity captured by `directory_identity()`.

- [ ] **Step 5: Prove the new primitive has no destructive dependency**

Run: `rg -n 'shutil|rmtree|rmdir|unlink|remove_directory' w3xtool/description_cache_publication_models.py w3xtool/description_cache_publication_retention_names.py w3xtool/description_cache_publication_retention.py w3xtool/description_cache_publication_retention_installed.py w3xtool/description_cache_publication_retention_recovery.py`

Expected: no matches. Leave the existing remover in `description_cache_publication_fs.py` until Task 2 migrates every import and call in the same green commit.

- [ ] **Step 6: Run focused tests and static checks**

Run: `uv run python -m pytest -q tests/test_description_cache_publication_retention.py tests/test_atomic_rename.py`

Expected: PASS, including the real source-name swap and collision preservation cases.

Run: `uv run --with ruff ruff check w3xtool/description_cache_publication_models.py w3xtool/description_cache_publication_retention_names.py w3xtool/description_cache_publication_retention.py w3xtool/description_cache_publication_retention_installed.py w3xtool/description_cache_publication_retention_recovery.py w3xtool/description_cache_publication_errors.py tests/test_description_cache_publication_retention.py`

Run: `uv run --with ruff ruff format --check w3xtool/description_cache_publication_models.py w3xtool/description_cache_publication_retention_names.py w3xtool/description_cache_publication_retention.py w3xtool/description_cache_publication_retention_installed.py w3xtool/description_cache_publication_retention_recovery.py w3xtool/description_cache_publication_errors.py tests/test_description_cache_publication_retention.py`

Run: `uv run --with basedpyright basedpyright --level error w3xtool/description_cache_publication_models.py w3xtool/description_cache_publication_retention_names.py w3xtool/description_cache_publication_retention.py w3xtool/description_cache_publication_retention_installed.py w3xtool/description_cache_publication_retention_recovery.py w3xtool/description_cache_publication_errors.py tests/test_description_cache_publication_retention.py`

- [ ] **Step 7: Hold the preservation slice until the complete behavioral suite is GREEN**

Do not commit Task 1 separately while the pre-implementation lifecycle/CLI tests are still RED. Run the primitive-focused checks, then continue directly into Task 2. Task 2 Step 11 stages the model, primitive, all nine prewritten behavior files, and lifecycle integration together only after the exact RED command from Step 2 is fully GREEN.

---

### Task 2: Non-destructive publication lifecycle and retained-result reporting

**Files:**
- Continue from Task 1: `w3xtool/description_cache_publication_models.py`
- Continue from Task 1: `w3xtool/description_cache_publication_retention_names.py`
- Continue from Task 1: `w3xtool/description_cache_publication_named_leaf.py`
- Continue from Task 1: `w3xtool/description_cache_publication_retention.py`
- Continue from Task 1: `w3xtool/description_cache_publication_retention_installed.py`
- Continue from Task 1: `w3xtool/description_cache_publication_retention_recovery.py`
- Continue from Task 1: `w3xtool/description_cache_publication_errors.py`
- Continue from Task 1: `tests/test_description_cache_publication_retention.py`
- Continue from Task 1: `tests/test_description_cache_retained_generations.py`
- Continue from Task 1: `tests/test_description_cache_publication_retention_collisions.py`
- Continue from Task 1: `tests/test_description_cache_publication_retention_durability.py`
- Continue from Task 1: `tests/test_description_cache_publication_retention_races.py`
- Continue from Task 1: `tests/test_description_cache_cli_retention.py`
- Continue from Task 1: `tests/test_description_cache_publication_recovery_durability.py`
- Continue from Task 1: `tests/test_description_cache_publication_stage_io.py`
- Continue from Task 1: `tests/test_description_cache_publication_descriptor_close.py`
- Create: `tests/test_description_cache_publication_imports.py`
- Create: `w3xtool/description_cache_publication_build.py`
- Create: `w3xtool/description_cache_publication_backup_finalization.py`
- Create: `w3xtool/description_cache_publication_descriptor_close.py`
- Create: `w3xtool/description_cache_publication_evidence.py`
- Create: `w3xtool/description_cache_publication_generation_evidence.py`
- Create: `w3xtool/description_cache_publication_parent_identity.py`
- Create: `w3xtool/description_cache_publication_private_attempt.py`
- Create: `w3xtool/description_cache_publication_recovery_state.py`
- Create: `w3xtool/description_cache_publication_retention_durability.py`
- Create: `w3xtool/description_cache_publication_result_evidence.py`
- Create: `w3xtool/description_cache_publication_rollback_selection.py`
- Create: `w3xtool/description_cache_publication_stage_finalization.py`
- Create: `w3xtool/description_cache_publication_stage_io.py`
- Create: `w3xtool/description_cache_publication_stage_location.py`
- Create: `w3xtool/description_cache_publication_stage_location_scan.py`
- Create: `w3xtool/description_cache_publication_stage_normalization.py`
- Create: `w3xtool/trusted_description_cache_generation_io.py`
- Modify: `tests/description_cache_publication_fixture.py`
- Modify: `tests/test_description_cache_publication.py`
- Modify: `tests/test_description_cache_publication_concurrency.py`
- Modify: `tests/test_description_cache_publication_parent_binding.py`
- Modify: `tests/test_description_cache_publication_validation.py`
- Modify: `tests/test_trusted_description_cache_anchored.py`
- Modify: `tests/test_atomic_rename.py`
- Modify: `w3xtool/atomic_rename.py`
- Modify: `w3xtool/description_cache_publication.py`
- Modify: `w3xtool/description_cache_owned_schema.py`
- Modify: `w3xtool/description_cache_publication_absent.py`
- Modify: `w3xtool/description_cache_publication_commit.py`
- Modify: `w3xtool/description_cache_publication_parent.py`
- Modify: `w3xtool/description_cache_publication_recovery.py`
- Modify: `w3xtool/description_cache_publication_replacement.py`
- Modify: `w3xtool/description_cache_publication_stage.py`
- Modify: `w3xtool/description_cache_publication_transaction.py`
- Modify: `w3xtool/description_cache_publication_fs.py`
- Modify: `w3xtool/trusted_description_cache.py`
- Modify: `w3xtool/trusted_description_cache_io.py`
- Modify: `w3xtool/trusted_description_cache_models.py`
- Modify: `w3xtool/description_cache_migration.py`
- Modify: `w3xtool/description_cache_migration_models.py`
- Modify: `w3xtool/description_cache_cli.py`

**Interfaces:**
- Changes: `publish_description_cache(...) -> DescriptionCachePublicationResult`.
- Changes internal `publish_valid_stage(...) -> DescriptionCachePublicationProof`; it borrows the already-held parent/stage descriptors, consumes `VerifiedDescriptionCacheGeneration`, performs a second complete held-stage reread/proof immediately before the first rename, preserves the exact previously validated cache digest in `RetainedCacheExpectation`, and passes one `RetainedCacheNames` object through the whole transaction instead of reopening either pathname. Public `publish_description_cache(...)` still returns `DescriptionCachePublicationResult` only after the proof boundary passes.
- Changes: `ParentBoundValidator` receives an already durable `RawRetain(parent_descriptor, path, expected, role)` and exposes `BoundRetain(path, expected, role)`; lifecycle modules consume only the three-argument bound form and never call the raw move primitive. Its existing `require_valid()` is also modified so validation failure precedes any later parent-proof ledger, and a parent error is bare-re-raised without cause replacement.
- Changes: `publish_absent()` retains a failed installed output as `failed-output` before re-raising.
- Changes: `restore_previous_generation()` retains the exactly recovered new generation as `failed-stage`; ambiguous objects use `recovery` and raise typed `NEEDS_CONTEXT`.
- Changes: `commit_replacement()` atomically retains the displaced verified backup as `previous`; the move is the irreversible namespace commit point, while process success is returned only after parent synchronization succeeds.
- Changes: final-stage handling renames a still-exact stage to `failed-stage`; it never unlinks or recursively removes it.
- Guarantees: once any retain call returns a record, every later parent-identity or fsync failure raises typed `NEEDS_CONTEXT` carrying its current re-proved form; a controlled rollback that consumes a retained name replaces that stale record with the object's new live record, and nested errors merge live evidence with stable de-duplication.
- Extends: `DescriptionCacheMigrationResult.retained: tuple[RetainedCacheRecord, ...] = ()` as a trailing compatibility field.
- Extends: CLI success output with one stable line per retained record: `保留对象：<role> -> <path>`.
- Produces: `require_atomic_rename_support()` and calls it before the stage-I/O preflight,
  transaction-ID allocation, descriptor-relative `mkdir`, stage build/writer, or either
  rename adapter, so an unsupported atomic API has zero publication effects.
- Produces: `BoundDescriptionCacheStage(parent_descriptor, stage_descriptor, stage, parent_identity, stage_identity)`, an owned context manager whose descriptors stay open across build and publication and whose `__exit__` only closes descriptors.
- Produces: `DescriptorCloseLedger`, `close_publication_descriptors(...)`, and `DescriptionCachePublicationError.append_close_context(detail, failures)`; the ledger stores the last publicly proved retained/transient evidence, both close operations are always attempted, and every exact close exception is appended in attempt order without replacing an in-flight typed subtype or cause.
- Produces: `descriptor_identity(descriptor)` in the stage module, requiring `fstat()` to describe a directory and returning its `(device, inode)` for both creation and transaction proofs.
- Changes: `create_stage_and_capture(stage, output, names, rename_noreplace, sync_parent)` opens and binds the publication parent, creates and opens the stage descriptor-relative with no-follow semantics, synchronizes the parent, and returns the bound context. Before closing on a creation failure it moves an exact proved directory to `failed-stage`, a generic proved object to `recovery`, or reports a transient only when safe normalization is impossible; every parent-loss boundary also freshly captures the descriptor-proved active `output` leaf. Its two pre-creation outer branches propagate a typed publication error with its existing ledger intact and seed a new one-element ledger only for an ordinary untyped exception; evidence finalization is followed by a raise without a replacement cause.
- Produces: `raise_normalized_stage_creation_failure(...) -> Never` and `capture_transient_record(...)` in `description_cache_publication_stage_normalization.py`; creation imports that one failure boundary without taking finalization responsibility.
- Produces: `finalize_private_artifacts(bound, backup, output, names, rename_noreplace, sync_parent, known_retained=(), known_transient=())` in `description_cache_publication_stage_finalization.py`; it independently attempts descriptor-proved normalization of both transient names, moving an exact held stage to `failed-stage` and any exact unexpected backup to `recovery`, then returns newly normalized live records or one merged typed error. Backup-attempt records/errors are merged into the stage locator's known evidence before the stage attempt begins, so one current path/inode is never simultaneously classified as retained and unrelated transient. Already published records remain separate known non-held evidence for the stage locator and are not reclassified as private results. Its private `retain_stage()` owns the held-stage distinction.
- Produces: `retain_backup(...)` in `description_cache_publication_backup_finalization.py` and `attempt_private(...)` plus immutable `PrivateAttempt` in `description_cache_publication_private_attempt.py`; typed operation errors are already authoritative evidence boundaries and pass through unchanged, while only ordinary exceptions receive one fresh fallback plus the exact exception in `failures`. The finalizer owns only two-attempt orchestration/evidence merge and remains below 200 pure LOC.
- Produces: `locate_consumed_stage(bound, output, names, *, known_retained=(), known_transient=(), prior_failures=(), later_retained=(), later_transient=(), detail=None) -> RetainedCacheRecord | None` in `description_cache_publication_stage_location.py`; every call scans output and all four legal retained names twice, keeps the unique held identity location separate from already published/non-held evidence, rejects any set change, appends exact parent/read/retention faults after `prior_failures`, adds a held transient only without one unique exact location, and never loses an exact held output after a foreign stage-leaf retention succeeds or fails. Its forced-error output probe carries the held identity only when output is that unique match. A clean replacement accepts `output=held-new` plus known `previous=old`.
- Produces internal immutable stage-location snapshots and their state/evidence conversions in `description_cache_publication_stage_location_scan.py`; each state carries `failure: OSError | None`, the locator imports them one-way, and both focused modules remain below 200 pure LOC.
- Produces one `TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY` in `description_cache_owned_schema.py`, computed by UTF-8 filename-byte order from the three payloads, manifest, and marker; writer, generation snapshot, payload read, public proof, and comparison use only that tuple.
- Produces: `TrustedCacheLeafProof(name, device, inode, size, mtime_ns, ctime_ns, mode, sha256)`, `TrustedCacheGenerationProof(directory_device, directory_inode, leaves)`, and `VerifiedDescriptionCacheGeneration(verified, proof)` in `trusted_description_cache_models.py`; `write_stage_text(stage_descriptor, display_root, name, text) -> TrustedCacheLeafProof` uses exclusive descriptor-relative no-follow file creation, complete writes, file fsync, and before/after regular-file device/inode/size/mtime/ctime/mode proof and never opens `display_root`.
- Produces: `require_stage_io_support()` which checks descriptor-relative `open`, `mkdir`,
  `stat`, descriptor `listdir`, no-follow stat, `O_DIRECTORY`, `O_EXCL`, and `O_NOFOLLOW`
  after atomic support succeeds but before transaction-ID allocation, descriptor-relative
  `mkdir`, stage build/writer, or either rename adapter.
- Produces: `load_trusted_description_cache_from_descriptor(stage_descriptor, display_root, expected_leaves) -> VerifiedDescriptionCacheGeneration`; one generation read stores each full `os.stat_result`, passes that object unchanged to `read_owned_regular_file()`, reads/hashes all five, then snapshots all five again and requires directory identity plus every leaf device/inode/size/`mtime_ns`/`ctime_ns`/mode/SHA-256 to stay exact. Public, held-parent, and held-stage loaders remain byte-for-byte equivalent through `.verified`.
- Produces: `require_stable_generation_set(parent_descriptor, parent, parent_identity, expected_generations, private_paths)` in `description_cache_publication_generation_evidence.py`. It opens and holds every active/expected-previous directory, snapshots all generations and both private names, reads and validates every payload, snapshots the entire set again, and then performs a second terminal set-wide read/hash round. Both rounds must validate to the exact pre-rename `VerifiedDescriptionCache` bytes, and the two terminal metadata/hash proof tuples must equal each other. A same-inode write to an early file or generation while a later one is read is therefore rejected; the contract does not claim pre-rename leaf-inode continuity for an already-owned previous cache that historically exposed only validated bytes.
- Produces: `retain_durably(...)` in `description_cache_publication_retention_durability.py`. It invokes the raw move once, fsyncs the held parent on both return and exception, re-proves all moved-error records, rechecks the public parent binding, and only then returns or re-raises. Every lifecycle/creation/finalization retention uses this wrapper.
- Produces `finalize_error_evidence(...)` and `require_live_retained_evidence(...)` in `description_cache_publication_evidence.py`; `read_named_leaf(...)`, `reprove_retained(...)`, `reprove_transient(...)`, and `capture_named_transient(...)` live in `description_cache_publication_named_leaf.py` and return immutable `RetainedEvidenceReproof` values carrying exact read failures. Produces `require_live_result_evidence(parent_descriptor, parent, parent_identity, output, output_identity, proof, private_paths) -> DescriptionCachePublicationResult` in the separate `description_cache_publication_result_evidence.py`. They merge and re-prove every retained leaf through the held parent descriptor, preserve replaced/unreadable names as transient evidence, append read failures in event order, and make `require_parent_identity()` the final filesystem operation after all leaf reproofs. The result boundary delegates active/`previous` bytes and terminal stage/backup absence to the generation-set proof rather than checking directory inodes after independent loaders. A lost public binding clears `retained`, converts every still-held retained leaf to transient without another filesystem read, and reports the currently descriptor-proved active output leaf as transient; no returned error/result may expose an unaddressable retained path.
- Produces: `select_live_identity_path(...)` in `description_cache_publication_rollback_selection.py`; rollback identity selection does not inflate the atomic-move or evidence modules.
- Clarifies: successful commands always leave zero stage/backup names; a typed failure also normalizes every identity it can still prove, but a no-replace target collision or filesystem-level atomic-rename rejection may intentionally leave a transient evidence name rather than overwrite or delete anything.

- [ ] **Step 1: Confirm the pre-implementation tests are split by behavior and remain RED**

These files were created before Task 1 production edits by the Task 1 Step 1 RED gate. Keep `tests/test_description_cache_retained_generations.py` limited to normal replacement, absent-output rollback, and loader non-discovery. Put namespace swaps, output takeovers, parent-binding races, and nested restoration errors in `tests/test_description_cache_publication_retention_races.py`. The nested-error case starts with records already attached to the original retention failure, forces restoration to fail with an overlapping record plus a new record, and requires the surfaced tuple to retain first-seen order with no duplicate `(path, role, device, inode)`. Add two explicit public-boundary races there: one loses the public parent binding after a `previous` record exists but before a successful result is returned; the other loses it after a failure record exists but before the error reaches the caller. Both require `retained == ()`, one transient record for each descriptor-proved retained leaf, the exact object still present below the displaced held parent, and the replacement public parent byte-for-byte untouched. Put all post-retain fsync and revalidation failures in `tests/test_description_cache_publication_retention_durability.py`. Put intended `previous`, `failed-output`, `failed-stage`, and `recovery` target collisions in `tests/test_description_cache_publication_retention_collisions.py`. Put all CLI stdout/stderr assertions in `tests/test_description_cache_cli_retention.py`; do not add a line to the warning-band `tests/test_description_cache_cli.py` (currently about 226 pure LOC). Every success/error test that observes retained records calls one shared assertion that performs `path.stat(follow_symlinks=False)` and requires each current `(st_dev, st_ino)` to equal `record.identity`; a consumed recovery record or a retained path below a lost public parent is therefore an immediate test failure. While touching `tests/test_description_cache_publication_concurrency.py`, replace its existing runtime type-check exception assertion with an exhaustive `match`/`assert_never` assertion without changing behavior. Reuse existing migration fixtures and keep each new file below 200 pure LOC.

```python
"""End-to-end retained-generation publication outcomes."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

from tests.description_cache_publication_fixture import replacement_inputs
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication as publication
from w3xtool.description_cache_migration import (
    DescriptionCacheMigrationOptions,
    migrate_description_cache,
)
from w3xtool.description_cache_publication import (
    DescriptionCachePublicationError,
)
from w3xtool.description_cache_publication_commit import (
    PublicationCommitContextError,
)
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def transient_publication_paths(output: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for pattern in (
            ".w3xray-description-cache-stage-*",
            ".w3xray-description-cache-backup-*",
        )
        for path in output.parent.glob(pattern)
    )


def retained_publication_paths(output: Path) -> tuple[Path, ...]:
    return tuple(
        output.parent.glob(".w3xray-description-cache-retained-*-*")
    )


def test_replacement_retains_exact_previous_inode_without_rmtree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    monkeypatch.delattr(shutil, "rmtree")
    result = migrate_description_cache(
        DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
    )

    assert result.retained == tuple(result.retained)
    assert len(result.retained) == 1
    retained = result.retained[0]
    assert retained.role.value == "previous"
    assert retained.identity == previous_identity == _identity(retained.path)
    assert load_trusted_description_cache(retained.path).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "first"
    assert load_trusted_description_cache(root).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "second"
    assert not transient_publication_paths(root)


def test_first_publication_validation_failure_retains_failed_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    installed_identity: list[tuple[int, int]] = []
    original = getattr(publication, "_require_valid_at")

    def reject_installed_output(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        if path == output:
            installed_identity.append(_identity(path))
            raise OSError("post-publication proof failed")
        return original(parent_descriptor, path)

    monkeypatch.setattr(publication, "_require_valid_at", reject_installed_output)
    with pytest.raises(
        DescriptionCachePublicationError,
        match="post-publication proof failed",
    ) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    retained = retained_publication_paths(output)
    assert not output.exists()
    assert len(installed_identity) == len(retained) == 1
    assert retained[0].name.endswith("-failed-output")
    assert _identity(retained[0]) == installed_identity[0]
    assert len(raised.value.retained) == 1
    assert raised.value.retained[0].role.value == "failed-output"
    assert raised.value.retained[0].identity == installed_identity[0]
    assert not transient_publication_paths(output)


def test_retention_race_returns_needs_context_and_preserves_every_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_previous = root.parent / "displaced-previous"
    decoy = root.parent / "retention-decoy"
    decoy.mkdir()
    decoy_identity = _identity(decoy)
    original = getattr(publication, "_rename_noreplace")
    raced = False

    def race_before_previous_retention(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal raced
        if not raced and destination_name.endswith("-previous"):
            raced = True
            os.rename(
                source_name,
                displaced_previous.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.rename(
                decoy.name,
                source_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        original(parent_descriptor, source_name, destination_name)

    monkeypatch.setattr(publication, "_rename_noreplace", race_before_previous_retention)
    with pytest.raises(
        PublicationCommitContextError,
        match="NEEDS_CONTEXT",
    ) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    assert raced
    assert _identity(displaced_previous) == previous_identity
    recovery = tuple(
        path
        for path in retained_publication_paths(root)
        if path.name.endswith("-recovery")
    )
    assert len(recovery) == 1
    assert _identity(recovery[0]) == decoy_identity
    assert any(
        record.role.value == "recovery"
        and record.identity == decoy_identity
        for record in raised.value.retained
    )
    assert not transient_publication_paths(root)
```

The first two tests above belong in `test_description_cache_retained_generations.py`; the retention-race test belongs in `test_description_cache_publication_retention_races.py`.

Add this completed-then-raised absent-output case to the focused race file. It fails against
the current base-error reconstruction even after the filesystem record is preserved:

```python
def test_absent_move_then_raise_keeps_commit_subtype_after_failed_output_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "_rename_noreplace")
    injected = False
    rename_error = RuntimeError("injected after absent-output install")

    def move_then_raise(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        nonlocal injected
        original(parent_descriptor, source_name, destination_name)
        if destination_name == output.name and not injected:
            injected = True
            raise rename_error

    monkeypatch.setattr(publication, "_rename_noreplace", move_then_raise)
    with pytest.raises(DescriptionCachePublicationError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert injected
    assert type(raised.value) is PublicationCommitContextError
    assert any(failure is rename_error for failure in raised.value.failures)
    assert not output.exists()
    assert len(raised.value.retained) == 1
    record = raised.value.retained[0]
    assert record.role.value == "failed-output"
    assert _identity(record.path) == record.identity
```

Keep descriptor-close faults in
`tests/test_description_cache_publication_descriptor_close.py`. The initial RED cases inject
a stage-descriptor close failure after a replacement has a live `previous` record and require
typed `NEEDS_CONTEXT` carrying that exact record while the parent close is still attempted;
inject both close failures while `RetainedObjectInstalledContextError` is already in flight
and require the same subtype plus byte-for-byte identical retained/transient tuples, the
unchanged pre-existing cause, and the exact stage-close then parent-close exception objects
appended in that order after the prior ledger; repeat both close faults after nominal success
and require both exact objects in the new typed error's ledger while the first is its sole
explicit cause; and
fault creation-failure cleanup after both descriptors exist, requiring both close attempts
and the already-normalized typed error. No test patches process-wide `os.close` during pytest
fixture cleanup: call the production close boundary through its injected close callable or a
focused publication seam. In the initial RED form, import the already-existing
`w3xtool.description_cache_publication_stage` module namespace and access the proposed close
boundary inside each test body, so collection succeeds and behavior fails at runtime. After
Task 1 defines the installed-target subtype, refactor the in-flight case to construct that
exact subtype without changing its assertions; the close helper remains missing until this
Task 2 step turns the same tests GREEN.

Keep stage-location set-proof races in
`tests/test_description_cache_publication_retention_races.py`. Add one normal replacement
whose known `previous=old` remains live while the held stage is uniquely `output=new`; one
abnormal move that places the held stage at the same transaction's `previous` leaf; and one
forced-error case with an unrelated already published retained record. In separate cases,
insert or replace `output` after the locator's first output read on a would-be clean return
and on a forced-error path. Every case requires the terminal scan's current output evidence,
no false held-stage transient when exactly one held location exists, and typed
`NEEDS_CONTEXT` for any between-scan change. The forced-error `previous` case asserts one
exact retained held-stage record, no stage/output transient whose `held_identity` equals that
record, and—when output is foreign—only a held-less current output transient. Pass that same
typed locator error through `attempt_private()` and require its complete retained/transient
tuples to remain byte-for-byte equal, proving the independent-attempt boundary does not add
a generic stage fallback. Add a backup-first case that moves an unexpected backup to
`recovery` and then makes stage normalization fail; require the backup record to be known by
the stage locator and require the final sets
`{(record.path, record.identity)}` and
`{(record.path, record.identity) for record in error.transient}` to be disjoint. Also inject ordinary failures at the
post-`mkdir` collision and top transaction boundaries and require
`raised.value.__cause__ is not raised.value`; the original injected exception must remain
reachable through the explicit cause/context chain or the ordered typed `failures` ledger.
For independent ordinary backup and stage failures, assert both exact exception objects are
present by identity in that ledger after the aggregate finalizer runs.

In `tests/test_description_cache_cli_retention.py`, add a success case that first publishes an active cache, then replaces it and requires the summary followed by the retained role/path line:

Add these imports beside the existing test fixtures:

```python
from tests.description_cache_publication_fixture import replacement_inputs
from tests.trusted_description_cache_fixture import published_cache
```

```python
def test_description_cache_cli_reports_retained_previous_generation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = published_cache(tmp_path / "first", raw="first")
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")

    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            str(legacy_output),
            "--legacy-cache",
            str(legacy_cache),
            "--output",
            str(output),
        )
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "接受 1" in captured.out
    retained_lines = tuple(
        line for line in captured.out.splitlines() if line.startswith("保留对象：")
    )
    assert len(retained_lines) == 1
    assert "previous" in retained_lines[0]
    assert str(output.parent) in retained_lines[0]
    assert captured.err == ""


def test_description_cache_cli_reports_retained_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    original = getattr(publication, "_require_valid_at")

    def reject_installed_output(
        parent_descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        if path == output:
            raise OSError("post-publication proof failed")
        return original(parent_descriptor, path)

    monkeypatch.setattr(publication, "_require_valid_at", reject_installed_output)
    code = cli.run_description_cache_cli(
        (
            "migrate",
            "--legacy-output",
            str(legacy_output),
            "--legacy-cache",
            str(legacy_cache),
            "--output",
            str(output),
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    retained_lines = tuple(
        line for line in captured.err.splitlines() if line.startswith("保留对象：")
    )
    assert len(retained_lines) == 1
    assert "failed-output" in retained_lines[0]
    assert str(output.parent) in retained_lines[0]
    assert captured.out == ""
```

This real CLI failure must be present in the initial RED gate and must not construct a proposed model. After Task 1 introduces the model, refactor string role checks to `RetainedCacheRole` only where that improves exhaustiveness. In the inherited stage-self-validation test, capture the typed error and require exactly one `failed-stage` record with the on-disk retained inode.

- [ ] **Step 2: Keep unsupported-host and all collision cases RED before lifecycle implementation**

Run: `uv run python -m pytest -q tests/test_atomic_rename.py tests/test_description_cache_retained_generations.py tests/test_description_cache_publication_retention_collisions.py tests/test_description_cache_publication_retention_durability.py tests/test_description_cache_publication_retention_races.py tests/test_description_cache_publication_recovery_durability.py tests/test_description_cache_publication_stage_io.py tests/test_description_cache_publication_descriptor_close.py tests/test_description_cache_cli_retention.py`

Expected: FAIL because replacement recursively removes the previous generation, first-publication rollback recursively removes the installed output, and neither migration result nor CLI exposes retained records.

The two publication-order preflight REDs belong in
`test_description_cache_retained_generations.py`. Import `importlib`, `Never`,
`DescriptionCachePublicationError`, the current publication-module namespace, and the
existing stage-module namespace. Resolve the new stage-I/O module inside its test body so
the pre-production failure stays runtime RED rather than collection failure. One test sets
`sys.platform` to `unsupported`; the other leaves atomic support intact and forces the
stage-I/O support contract unavailable. Both invoke a real migration and use the same
instrumentation helper to require zero calls to `uuid4`, descriptor-relative `mkdir`, the
stage build/writer boundary, no-replace, and exchange. They also require no active,
transient, or retained name. These counter assertions make the tests RED against any
create-then-clean-up or partially ordered implementation; eventual namespace absence alone
is insufficient. Add separate direct support-contract REDs to `tests/test_atomic_rename.py`
and `tests/test_description_cache_publication_stage_io.py` as shown after this fixture. Add
the adversarial namespace cases following these tests to
`test_description_cache_publication_retention_collisions.py` using the existing real
rename/exchange adapters:

```python
def _instrument_preflight_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    calls = {
        "uuid4": 0,
        "mkdir": 0,
        "writer": 0,
        "rename_noreplace": 0,
        "rename_exchange": 0,
    }

    def forbidden_uuid4() -> Never:
        calls["uuid4"] += 1
        raise AssertionError("UUID allocation ran before support preflight")

    def forbidden_mkdir(
        _name: str,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> Never:
        del mode, dir_fd
        calls["mkdir"] += 1
        raise AssertionError("stage mkdir ran before support preflight")

    def forbidden_writer(*_args: object, **_kwargs: object) -> Never:
        calls["writer"] += 1
        raise AssertionError("stage writer ran before support preflight")

    def forbidden_noreplace(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_noreplace"] += 1
        raise AssertionError("no-replace ran before support preflight")

    def forbidden_exchange(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_exchange"] += 1
        raise AssertionError("exchange ran before support preflight")

    monkeypatch.setattr(publication, "uuid4", forbidden_uuid4)
    monkeypatch.setattr(publication_stage.os, "mkdir", forbidden_mkdir)
    monkeypatch.setattr(
        publication,
        "build_description_cache_stage",
        forbidden_writer,
    )
    monkeypatch.setattr(publication, "_rename_noreplace", forbidden_noreplace)
    monkeypatch.setattr(publication, "_rename_exchange", forbidden_exchange)
    return calls


def test_atomic_rename_unsupported_fails_before_any_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    calls = _instrument_preflight_effects(monkeypatch)
    monkeypatch.setattr(sys, "platform", "unsupported")

    with pytest.raises(AtomicRenameUnavailableError):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert calls == dict.fromkeys(calls, 0)
    assert not output.exists()
    assert not transient_publication_paths(output)
    assert not retained_publication_paths(output)


def test_stage_io_unsupported_fails_before_any_publication_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "first")
    output = tmp_path / "trusted"
    stage_io = importlib.import_module(
        "w3xtool.description_cache_publication_stage_io"
    )
    calls = _instrument_preflight_effects(monkeypatch)
    monkeypatch.setattr(stage_io, "_STAGE_IO_AVAILABLE", False)

    with pytest.raises(
        DescriptionCachePublicationError,
        match="descriptor-anchored trusted-cache stage I/O is unavailable",
    ):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, output)
        )

    assert calls == dict.fromkeys(calls, 0)
    assert not output.exists()
    assert not transient_publication_paths(output)
    assert not retained_publication_paths(output)


def test_previous_role_collision_restores_active_and_retains_failed_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    original_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    rename_noreplace = getattr(publication, "_rename_noreplace")
    collisions: list[tuple[Path, tuple[int, int]]] = []

    def collide_with_previous_role(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        if destination_name.endswith("-previous") and not collisions:
            collision = root.parent / destination_name
            collision.mkdir()
            (collision / "foreign.txt").write_text("foreign", encoding="utf-8")
            collisions.append((collision, _identity(collision)))
        rename_noreplace(parent_descriptor, source_name, destination_name)

    monkeypatch.setattr(
        publication,
        "_rename_noreplace",
        collide_with_previous_role,
    )
    with pytest.raises(PublicationCommitContextError) as raised:
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    assert _identity(root) == original_identity
    assert load_trusted_description_cache(root).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "first"
    assert len(collisions) == 1
    collision, collision_identity = collisions[0]
    assert _identity(collision) == collision_identity
    failed = tuple(
        path
        for path in retained_publication_paths(root)
        if path.name.endswith("-failed-stage")
    )
    assert len(failed) == 1
    assert load_trusted_description_cache(failed[0]).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "second"
    assert any(
        record.role.value == "failed-stage"
        for record in raised.value.retained
    )
    assert all(
        _identity(record.path) == record.identity
        for record in raised.value.retained
    )
    assert not any(
        record.role.value == "recovery"
        for record in raised.value.retained
    )
    assert not transient_publication_paths(root)


def test_recovery_role_collision_preserves_transient_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = published_cache(tmp_path / "first", raw="first")
    previous_identity = _identity(root)
    legacy_output, legacy_cache = replacement_inputs(tmp_path, "second")
    displaced_new = root.parent / "displaced-new"
    collisions: list[tuple[Path, tuple[int, int]]] = []

    def takeover_with_recovery_collision(
        parent_descriptor: int,
        source_name: str,
        destination_name: str,
    ) -> None:
        exchange_in_parent(parent_descriptor, source_name, destination_name)
        transaction_id = source_name.removeprefix(
            ".w3xray-description-cache-stage-"
        )
        collision = root.parent / (
            ".w3xray-description-cache-retained-"
            f"{transaction_id}-recovery"
        )
        collision.mkdir()
        (collision / "foreign.txt").write_text("foreign", encoding="utf-8")
        collisions.append((collision, _identity(collision)))
        os.rename(
            destination_name,
            displaced_new.name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
        )
        root.mkdir()
        (root / "foreign.txt").write_text("winner", encoding="utf-8")

    monkeypatch.setattr(
        publication,
        "_rename_exchange",
        takeover_with_recovery_collision,
    )
    with pytest.raises(PublicationCommitContextError, match="NEEDS_CONTEXT"):
        migrate_description_cache(
            DescriptionCacheMigrationOptions(legacy_output, legacy_cache, root)
        )

    assert (root / "foreign.txt").read_text(encoding="utf-8") == "winner"
    assert load_trusted_description_cache(displaced_new).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "second"
    assert len(collisions) == 1
    collision, collision_identity = collisions[0]
    assert _identity(collision) == collision_identity
    transient = transient_publication_paths(root)
    assert len(transient) == 1
    assert _identity(transient[0]) == previous_identity
    assert load_trusted_description_cache(transient[0]).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "first"
```

Add `sys`, `AtomicRenameUnavailableError`, and `exchange_in_parent` to the respective focused test imports. Add two real primitive/lifecycle cases in the collision file for an occupied `failed-output` target and an occupied `failed-stage` target while `recovery` remains free: each must preserve the foreign collision, move the exact source inode to the same transaction's `recovery` name, raise typed `NEEDS_CONTEXT` carrying that recovery record, and leave zero stage/backup names. These cases use captured `(device, inode)` values rather than name-only assertions.

- [ ] **Step 3: Replace the remover injection with one parent-bound retention callable**

Before editing lifecycle code, use this state table as the required postcondition ledger. `N` is the staged new inode, `O` the previously active verified inode, and `F` a concurrent foreign object:

| Failure point | Proven state before handling | Required final names | Return |
|---|---|---|---|
| stage build/self-validation | `stage=N`; output unchanged | `failed-stage=N` | typed original failure carrying the record |
| absent publish post-proof | `output=N`; no stage | output absent; `failed-output=N` | typed failure carrying the record |
| exchange primitive fails before mutation | `output=O`, `stage=N` | `output=O`, `failed-stage=N` | typed failure carrying the record |
| post-exchange proof fails, names exact | `output=N`, `stage=O` | reverse to `output=O`, then `failed-stage=N` | typed failure carrying the record |
| output takeover after exchange | `output=F`, `stage=O`, `N` at attacker-chosen name | keep `output=F` and external `N`; move exact `stage=O` to `recovery` | `NEEDS_CONTEXT` carrying recovery record |
| proof fails after stage→backup | `output=N`, `backup=O` | reverse to `output=O`; normalize `backup=N` to `failed-stage` | typed failure carrying the record |
| intended previous retention is observed, then parent sync/binding/evidence fails | `output=N`, `previous=O`; commit boundary crossed | preserve both exact names; never reverse exchange or consume `previous` | `RetainedObjectInstalledContextError` carrying current evidence; never exit `0` |
| normal replacement | `output=N`, `previous=O` | both exact names, parent sync succeeds | success carrying previous record |
| `previous` collision, recovery free | `output=N`, source `backup=O`, intended retained name occupied | generic retainer moves `O` to `recovery`; rollback selects that unique live identity from the typed error, restores `output=O`, then retains `N` as `failed-stage` | typed failure containing live `failed-stage` and no stale `recovery`; zero transient names |
| `failed-output`/`failed-stage` collision, recovery free | source identity exact, intended retained name occupied | preserve collision; move the exact source to `recovery` | typed `NEEDS_CONTEXT` carrying the live recovery record; zero transient names |
| unexpected backup leaf at final boundary | backup identity exact; stage handled independently | move backup to `recovery`; still attempt exact stage normalization | typed `NEEDS_CONTEXT` with all live records; success is forbidden while either transient leaf remains |
| non-rollback role and recovery both occupied, atomic no-replace rejected, or exact rollback cannot be proved | exact source remains but no legal atomic retained move exists | preserve source transient plus every collision | typed `NEEDS_CONTEXT`; integrity reports transient violation |
| publication parent pathname loses its captured binding | held objects remain under the displaced parent; replacement parent is untrusted | do not mutate either parent by guessed pathname; preserve every reachable name | typed `NEEDS_CONTEXT`; operator supplies recovery context |
| stage leaf changes after capture | held stage descriptor remains `N`; named leaf is foreign or absent | build only through held `N`; do not mutate the named foreign leaf; preserve/record every reachable object | typed `NEEDS_CONTEXT`; foreign tree remains byte-for-byte unchanged |

No row authorizes deletion. A transient name is acceptable only in an impossible-normalization row (occupied destinations, rejected atomic operation, lost parent binding, or unknown/moved leaf), never on success and never when the exact object and a free retained role are both provable.

Add `require_atomic_rename_support()` to `w3xtool/atomic_rename.py`. It loads the platform's existing rename symbol without mutating the filesystem and requires both no-replace/exchange support. Add `require_stage_io_support()` to the focused stage-I/O module for every descriptor capability listed in Task 2's interfaces. `publish_description_cache()` invokes the atomic preflight and then the stage-I/O preflight before `uuid4()`, descriptor-relative `mkdir`, the stage build/writer, no-replace, or exchange. Unknown/insufficient hosts fail closed and create no evidence path. A later filesystem-level `ENOTSUP` remains the impossible-normalization row above.

Add this runtime RED to `tests/test_atomic_rename.py`; import the existing module namespace so the missing preflight symbol fails inside the test body rather than during collection:

```python
def test_atomic_rename_support_preflight_rejects_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_calls: list[None] = []

    def forbidden_call(
        _symbol: str,
        _source_descriptor: int,
        _source_name: str,
        _destination_descriptor: int,
        _destination_name: str,
        _flags: int,
    ) -> None:
        adapter_calls.append(None)

    monkeypatch.setattr(sys, "platform", "unsupported")
    monkeypatch.setattr(atomic_rename, "_call", forbidden_call)

    with pytest.raises(AtomicRenameUnavailableError):
        getattr(atomic_rename, "require_atomic_rename_support")()

    assert adapter_calls == []
```

It requires `AtomicRenameUnavailableError` before any `_call()` adapter invocation. Refactor the existing symbol lookup into one typed internal function shared by preflight, no-replace, and exchange so the production module remains below 200 pure LOC.

Add the analogous runtime RED to
`tests/test_description_cache_publication_stage_io.py`. Import `importlib`, `Never`, the
publication module namespace, and `DescriptionCachePublicationError`; resolve the new
stage-I/O module inside the test body so the pre-production failure is runtime RED rather
than collection failure:

```python
def test_stage_io_support_preflight_rejects_incomplete_host_without_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_io = importlib.import_module(
        "w3xtool.description_cache_publication_stage_io"
    )
    calls = {
        "uuid4": 0,
        "rename_noreplace": 0,
        "rename_exchange": 0,
    }

    def forbidden_uuid4() -> Never:
        calls["uuid4"] += 1
        raise AssertionError("stage-I/O preflight entered a transaction")

    def forbidden_noreplace(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_noreplace"] += 1
        raise AssertionError("stage-I/O preflight called no-replace")

    def forbidden_exchange(
        _parent_descriptor: int,
        _source_name: str,
        _destination_name: str,
    ) -> Never:
        calls["rename_exchange"] += 1
        raise AssertionError("stage-I/O preflight called exchange")

    monkeypatch.setattr(stage_io, "_STAGE_IO_AVAILABLE", False)
    monkeypatch.setattr(publication, "uuid4", forbidden_uuid4)
    monkeypatch.setattr(publication, "_rename_noreplace", forbidden_noreplace)
    monkeypatch.setattr(publication, "_rename_exchange", forbidden_exchange)

    with pytest.raises(
        DescriptionCachePublicationError,
        match="descriptor-anchored trusted-cache stage I/O is unavailable",
    ):
        getattr(stage_io, "require_stage_io_support")()

    assert calls == dict.fromkeys(calls, 0)
```

This direct contract test proves rejection without transaction allocation or either rename
adapter. Together with the two real-migration tests, it closes both the low-level support
contract and the full zero-effect publication ordering. Keep both focused test files in the
Step 2 RED command and the complete Task 5 lane.

Move `parent_descriptor_identity()` and `require_parent_identity()` into the focused `description_cache_publication_parent_identity.py`, update every import, and leave `description_cache_publication_parent.py` responsible only for bound validation/retention. This removes the former `parent -> evidence -> parent` cycle and lets every caller use one evidence boundary:

```python
"""Identity proof for one held publication parent."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_fs import DirectoryIdentity


def parent_descriptor_identity(parent_descriptor: int) -> DirectoryIdentity:
    """Return the directory identity held by one open descriptor."""
    try:
        details = os.fstat(parent_descriptor)
    except OSError as exc:
        raise PublicationCommitContextError(
            "publication parent descriptor is unreadable; NEEDS_CONTEXT",
            failures=(exc,),
        ) from exc
    if not stat.S_ISDIR(details.st_mode):
        raise PublicationCommitContextError(
            "publication parent descriptor is not a directory; NEEDS_CONTEXT"
        )
    return details.st_dev, details.st_ino


def require_parent_identity(
    parent_descriptor: int,
    parent: Path,
    expected: DirectoryIdentity,
) -> None:
    """Prove a pathname still resolves to the exact held parent directory."""
    held = parent_descriptor_identity(parent_descriptor)
    try:
        named = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PublicationCommitContextError(
            "publication parent pathname is unavailable; NEEDS_CONTEXT",
            failures=(exc,),
        ) from exc
    named_identity = named.st_dev, named.st_ino
    if (
        not stat.S_ISDIR(named.st_mode)
        or held != expected
        or named_identity != expected
    ):
        raise PublicationCommitContextError(
            "publication parent identity changed; NEEDS_CONTEXT"
        )


__all__ = ("parent_descriptor_identity", "require_parent_identity")
```

Create `description_cache_publication_retention_durability.py` as the mandatory adapter around the raw no-replace primitive. It synchronizes after both a normal return and an exception because `retain_object()` may have successfully moved a source to `recovery` before raising. It captures the source leaf afresh after that sync attempt, not before it, and refuses a nominal success if the source name was reacquired between the raw primitive's proof and the durable boundary. When a raw error leaves its source name exact, it records that still-reachable leaf as transient evidence; an occupied recovery target or rejected atomic move may therefore never disappear from CLI evidence:

```python
"""Durable caller boundary around atomic retention moves."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Never, assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
    installed_context_error,
    merge_failures,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_named_leaf import capture_named_transient
from .description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_retention import retain_object
from .description_cache_publication_retention_names import RetainedCacheNames


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def retain_durably(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    source: Path,
    expected: DirectoryIdentity,
    names: RetainedCacheNames,
    role: RetainedCacheRole,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> RetainedCacheRecord:
    """Move once, synchronize every outcome, and return only live evidence."""
    try:
        retained = retain_object(
            parent_descriptor,
            parent_identity,
            source,
            expected,
            names,
            role,
            rename_noreplace,
        )
    except RetainedObjectInstalledContextError as installed_error:
        _synchronize_installed_error(
            parent_descriptor,
            parent,
            parent_identity,
            source,
            installed_error,
            sync_parent,
        )
    except Exception as retention_cause:  # noqa: BROAD_EXCEPT_OK - durable retention
        match retention_cause:
            case DescriptionCachePublicationError() as publication_error:
                retention_error = publication_error
            case Exception() as ordinary_error:
                retention_error = PublicationCommitContextError(
                    f"retention raised an ordinary exception: {ordinary_error}; "
                    "NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        try:
            sync_parent(parent_descriptor)
        except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - durability sync
            source_evidence = capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                source,
            )
            context_error = PublicationCommitContextError(
                "retention error could not be durably synchronized; NEEDS_CONTEXT",
                retention_error.retained,
                (*retention_error.transient, *source_evidence.transient),
                merge_failures(
                    merge_failures(
                        (*retention_error.failures, retention_error),
                        (sync_error,),
                    ),
                    source_evidence.failures,
                ),
            )
            finalized = finalize_error_evidence(
                parent_descriptor,
                parent,
                parent_identity,
                context_error,
            )
            raise finalized
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            retention_error,
            later_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                source,
            ),
        )
    try:
        sync_parent(parent_descriptor)
    except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - durability sync
        source_evidence = capture_named_transient(
            parent_descriptor,
            parent,
            parent_identity,
            source,
        )
        context_error = PublicationCommitContextError(
            "retained object could not be durably synchronized; NEEDS_CONTEXT",
            (retained,),
            source_evidence.transient,
            merge_failures((sync_error,), source_evidence.failures),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
        raise installed_context_error(retained, finalized)
    source_evidence = capture_named_transient(
        parent_descriptor,
        parent,
        parent_identity,
        source,
    )
    if source_evidence.transient or source_evidence.failures:
        context_error = PublicationCommitContextError(
            "retention source name was reacquired before durability boundary; "
            "NEEDS_CONTEXT",
            (retained,),
            source_evidence.transient,
            source_evidence.failures,
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
        raise installed_context_error(retained, finalized)
    try:
        live = require_live_retained_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            (retained,),
        )
    except Exception as evidence_cause:  # noqa: BROAD_EXCEPT_OK - evidence boundary
        match evidence_cause:
            case DescriptionCachePublicationError() as publication_error:
                evidence_error = publication_error
            case Exception() as ordinary_error:
                evidence_error = PublicationCommitContextError(
                    f"retained-evidence proof raised an ordinary exception: "
                    f"{ordinary_error}; NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            evidence_error,
        )
        raise installed_context_error(retained, finalized)
    return live[0]


def _synchronize_installed_error(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    source: Path,
    installed_error: RetainedObjectInstalledContextError,
    sync_parent: Sync,
) -> Never:
    try:
        sync_parent(parent_descriptor)
    except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - installed sync
        context_error = PublicationCommitContextError(
            "installed retained target could not be durably synchronized; "
            "NEEDS_CONTEXT",
            installed_error.retained,
            installed_error.transient,
            merge_failures(
                (*installed_error.failures, installed_error), (sync_error,)
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
            later_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                source,
            ),
        )
        raise installed_context_error(installed_error.installed, finalized)
    finalized = finalize_error_evidence(
        parent_descriptor,
        parent,
        parent_identity,
        installed_error,
        later_evidence=capture_named_transient(
            parent_descriptor,
            parent,
            parent_identity,
            source,
        ),
    )
    raise installed_context_error(installed_error.installed, finalized)


__all__ = ("retain_durably",)
```

Confirm the initial Task 1 RED suite already contains focused cases for: intended-role collision followed by recovery move and parent-fsync failure; raw atomic rejection with the exact source still named; occupied `recovery` with exact failed output still at `output`; source-name reacquisition after both raw success and raw error but before the durable boundary; and parent loss after a moved-error record. Add a dedicated `previous` case where the raw intended move returns, the immediately following parent fsync fails, and an exchange-call counter proves rollback is never invoked: active remains `N`, intended `previous` remains `O`, every surfaced retained record is live, and the error is `RetainedObjectInstalledContextError`. Repeat the no-rollback assertion for parent-binding/evidence failure after the intended target was observed. Every case requires a sync attempt, typed `NEEDS_CONTEXT`, only live retained records, and a freshly re-proved transient record for every still-named exact source. Run those cases and record their expected behavioral failures before creating this module. A success or error record may not escape this adapter until `require_live_retained_evidence()` has passed, and the installed subtype may never be collapsed back into a rollback-eligible base error.

Create `description_cache_publication_rollback_selection.py` for the unique rollback-name proof formerly bundled into the oversized retention module:

```python
"""Select the one live name that can participate in an exact rollback."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_named_leaf import (
    read_named_leaf,
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
)


def select_live_identity_path(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    candidates: tuple[Path, ...],
    expected: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
    transient: tuple[PublicationTransientRecord, ...],
) -> Path:
    """Return the unique current name for one rollback identity."""
    if not candidates:
        raise _selection_error(
            "previous generation has no rollback candidates; NEEDS_CONTEXT",
            parent_descriptor,
            parent,
            parent_identity,
            records,
            transient,
            (),
        )
    expected_parent = candidates[0].parent
    live: list[Path] = []
    failures: tuple[Exception, ...] = ()
    for path in dict.fromkeys(candidates):
        if path.parent != expected_parent:
            continue
        proof = read_named_leaf(parent_descriptor, path.name)
        failures = merge_failures(failures, proof.failures)
        if proof.identity == expected:
            live.append(path)
    if failures or len(live) != 1:
        raise _selection_error(
            "previous generation has no unique live rollback name; NEEDS_CONTEXT",
            parent_descriptor,
            parent,
            parent_identity,
            records,
            transient,
            failures,
        )
    return live[0]


def _selection_error(
    detail: str,
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
    transient: tuple[PublicationTransientRecord, ...],
    failures: tuple[Exception, ...],
) -> PublicationCommitContextError:
    proof = reprove_retained(
        parent_descriptor,
        parent,
        parent_identity,
        records,
    )
    current_transient = reprove_transient(
        parent_descriptor,
        parent,
        parent_identity,
        (*transient, *proof.transient),
    )
    return PublicationCommitContextError(
        detail,
        proof.retained,
        current_transient.transient,
        merge_failures(
            failures,
            (*proof.failures, *current_transient.failures),
        ),
    )


__all__ = ("select_live_identity_path",)
```

The selector receives the retention error's transient tuple as a first-class input. Both
failure exits rebuild that tuple together with any retained-record proof loss; neither the
commit caller nor the selector may replace it with `proof.transient` alone.

In `description_cache_publication_parent.py`, replace the `Remove` type and `remover` field with two deliberately distinct signatures:

```python
type RawRetain = Callable[
    [int, Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]
type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]


@dataclass(frozen=True, slots=True)
class ParentBoundValidator:
    parent_descriptor: int
    parent: Path
    parent_identity: DirectoryIdentity
    validator: ValidateAt
    retainer: RawRetain

    def require_current_parent(self) -> None:
        """Require the public parent name to remain bound to the held directory."""
        require_parent_identity(
            self.parent_descriptor,
            self.parent,
            self.parent_identity,
        )

    def require_valid(self, path: Path) -> VerifiedDescriptionCache:
        """Validate one cache only while its parent remains exactly bound."""
        if path.parent != self.parent:
            raise PublicationCommitContextError(
                "cache validation escaped the held publication parent; "
                "NEEDS_CONTEXT"
            )
        self.require_current_parent()
        try:
            verified = self.validator(self.parent_descriptor, path)
        except OSError as validation_error:
            try:
                self.require_current_parent()
            except PublicationCommitContextError as parent_error:
                parent_error.replace_failures(
                    merge_failures(
                        (validation_error,),
                        parent_error.failures,
                    )
                )
                raise
            raise
        self.require_current_parent()
        return verified

    def retain(
        self,
        path: Path,
        expected: DirectoryIdentity,
        role: RetainedCacheRole,
    ) -> RetainedCacheRecord:
        if path.parent != self.parent:
            raise PublicationCommitContextError(
                "retention escaped the held publication parent; NEEDS_CONTEXT"
            )
        self.require_current_parent()
        retained = self.retainer(
            self.parent_descriptor,
            path,
            expected,
            role,
        )
        try:
            self.require_current_parent()
        except DescriptionCachePublicationError as context_error:
            finalized = finalize_error_evidence(
                self.parent_descriptor,
                self.parent,
                self.parent_identity,
                context_error,
                earlier_retained=(retained,),
            )
            raise installed_context_error(retained, finalized)
        return retained
```

Import `installed_context_error` and `merge_failures` from the errors module in
`description_cache_publication_parent.py`. On validation plus parent-proof failure, the
validation object precedes the parent error's existing ledger and bare `raise` preserves the
parent error's existing cause. The surfaced parent error is not appended to its own ledger.
For retained installation, the wrapper ledger contains the exact `finalized`
object after all of its failures, so a reproof/parent error returned by finalization and that
object's existing cause cannot disappear behind the earlier `context_error`.

In `description_cache_publication_transaction.py`, construct the callable from the same transaction names and no-replace primitive:

```python
def _raw_retain(
    parent_descriptor: int,
    path: Path,
    expected: DirectoryIdentity,
    role: RetainedCacheRole,
) -> RetainedCacheRecord:
    return retain_durably(
        parent_descriptor,
        output.parent,
        parent_identity,
        path,
        expected,
        retained_names,
        role,
        rename_noreplace,
        sync_parent,
    )
```

Construct `ParentBoundValidator` with `_raw_retain` and pass its three-argument bound method `binding.retain` to every lifecycle function. These are the exact ordered parameters after removing every `_Remove`/`Remove` alias and remover parameter:

Import `merge_retained` only where event-ordered error records are combined; import `reprove_retained`, `retained_as_transient`, and public boundary functions from `description_cache_publication_evidence.py` rather than the raw move module. Every merge call must state the earlier tuple first and later tuple second; direct retained-tuple concatenation or reversed merge order is forbidden.

| Function | Ordered parameters | Return |
|---|---|---|
| `publish_valid_stage` | `parent_descriptor, stage_descriptor, stage, stage_identity, stage_generation, output, backup, names, parent_identity, rename_noreplace, rename_exchange, require_valid_at, sync_parent` | `DescriptionCachePublicationProof` |
| `publish_absent` | `parent_descriptor, parent_identity, stage, output, stage_identity, stage_verified, rename_noreplace, require_valid, retain: BoundRetain, sync_parent` | `DescriptionCachePublicationProof` |
| `publish_replacement` | `parent_descriptor, parent_identity, stage, stage_identity, stage_verified, output, output_identity, previous_verified, backup, names, rename_exchange, rename_noreplace, require_valid, retain: BoundRetain, sync_parent` | `DescriptionCachePublicationProof` |
| `restore_previous_generation` | `parent_descriptor, parent_identity, output, staged_identity, recovery, previous_identity, stage, names, rename_exchange, rename_noreplace, require_valid, retain: BoundRetain, sync_parent, prior_records, prior_transient, detail` | `RetainedCacheRecord` |
| `commit_replacement` | `parent_descriptor, parent_identity, output, output_identity, backup, backup_identity, stage, names, verified, previous_verified, rename_exchange, rename_noreplace, require_valid, retain: BoundRetain, sync_parent` | `DescriptionCachePublicationProof` |

`publish_valid_stage()` borrows both descriptors and does not close them. Before dispatch it proves `parent_descriptor_identity(parent_descriptor) == parent_identity`, the public parent pathname has the same identity, `descriptor_identity(stage_descriptor) == stage_identity`, and `directory_identity(parent_descriptor, stage.name) == stage_identity`. It then calls `load_trusted_description_cache_from_descriptor(stage_descriptor, stage, stage_generation.proof.leaves)` again and requires the complete returned generation—including all five device/inode/size/mtime/ctime/mode/hash proofs and validated bytes—to equal `stage_generation`. Only then does it pass `stage_generation.verified` to absent/replacement publication. Existing-output validation remains through `ParentBoundValidator.require_valid()`; every subsequent stage/backup/output proof remains descriptor-relative to the same borrowed parent.

- [ ] **Step 4: Make absent publication retain a failed installed output**

Change `publish_absent()` to return a publication result and preserve rollback evidence:

```python
def publish_absent(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    stage: Path,
    output: Path,
    stage_identity: DirectoryIdentity,
    stage_verified: VerifiedDescriptionCache,
    rename_noreplace: Rename,
    require_valid: Validate,
    retain: BoundRetain,
    sync_parent: Sync,
) -> DescriptionCachePublicationProof:
    post_install_error: DescriptionCachePublicationError | None = None
    try:
        rename_noreplace(parent_descriptor, stage.name, output.name)
    except Exception as rename_cause:  # noqa: BROAD_EXCEPT_OK - install reproof
        installed, rename_error = _reprove_absent_install(
            parent_descriptor,
            parent_identity,
            stage,
            output,
            stage_identity,
        )
        rename_error.replace_failures(
            merge_failures((rename_cause,), rename_error.failures)
        )
        if not installed:
            raise rename_error from rename_cause
        post_install_error = rename_error
    try:
        if post_install_error is not None:
            raise post_install_error
        sync_parent(parent_descriptor)
        published = require_valid(output)
        _require_identity(parent_descriptor, output.name, stage_identity)
        if published != stage_verified:
            raise DescriptionCachePublicationError(
                "published output differs from the descriptor-verified stage"
            )
    except Exception as cause:  # noqa: BROAD_EXCEPT_OK - post-install retention
        match cause:
            case DescriptionCachePublicationError() as typed_error:
                publication_error = typed_error
            case Exception() as ordinary_error:
                publication_error = DescriptionCachePublicationError(
                    str(ordinary_error),
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        try:
            retained = retain(
                output,
                stage_identity,
                RetainedCacheRole.FAILED_OUTPUT,
            )
        except Exception as retention_cause:  # noqa: BROAD_EXCEPT_OK - retain boundary
            match retention_cause:
                case DescriptionCachePublicationError() as typed_error:
                    retention_error = typed_error
                case Exception() as ordinary_error:
                    retention_error = PublicationCommitContextError(
                        f"failed-output retention raised an ordinary exception: "
                        f"{ordinary_error}; NEEDS_CONTEXT",
                        failures=(ordinary_error,),
                    )
                case unreachable:
                    assert_never(unreachable)
            detail = (
                f"{publication_error}; failed-output retention failed: "
                f"{retention_error}; NEEDS_CONTEXT"
            )
            retained_evidence = merge_retained(
                publication_error.retained,
                retention_error.retained,
            )
            transient_evidence = tuple(
                dict.fromkeys(
                    (
                        *publication_error.transient,
                        *retention_error.transient,
                    )
                )
            )
            failure_evidence = merge_failures(
                (*publication_error.failures, publication_error),
                (*retention_error.failures, retention_error),
            )
            match retention_error:
                case RetainedObjectInstalledContextError(installed=installed):
                    combined_error = RetainedObjectInstalledContextError(
                        installed,
                        detail,
                        retained_evidence,
                        transient_evidence,
                        failure_evidence,
                    )
                case DescriptionCachePublicationError():
                    combined_error = PublicationCommitContextError(
                        detail,
                        retained_evidence,
                        transient_evidence,
                        failure_evidence,
                    )
                case unreachable:
                    assert_never(unreachable)
            raise combined_error from retention_cause
        publication_error.replace_retained(
            merge_retained(publication_error.retained, (retained,))
        )
        if publication_error is not cause:
            publication_error.replace_failures(
                merge_failures(publication_error.failures, (cause,))
            )
        raise publication_error
    return DescriptionCachePublicationProof(
        DescriptionCachePublicationResult(stage_verified)
    )


def _reprove_absent_install(
    parent_descriptor: int,
    parent_identity: DirectoryIdentity,
    stage: Path,
    output: Path,
    expected: DirectoryIdentity,
) -> tuple[bool, DescriptionCachePublicationError]:
    output_evidence = capture_named_transient(
        parent_descriptor,
        output.parent,
        parent_identity,
        output,
    )
    stage_evidence = capture_named_transient(
        parent_descriptor,
        stage.parent,
        parent_identity,
        stage,
    )
    output_identity = (
        output_evidence.transient[0].identity
        if output_evidence.transient
        else None
    )
    stage_identity = (
        stage_evidence.transient[0].identity
        if stage_evidence.transient
        else None
    )
    installed = bool(
        output_identity == expected
        and stage_identity != expected
    )
    return installed, PublicationCommitContextError(
        "absent-output rename completion required namespace reproof; "
        "NEEDS_CONTEXT",
        transient=tuple(
            dict.fromkeys(
                (*output_evidence.transient, *stage_evidence.transient)
            )
        ),
        failures=merge_failures(
            output_evidence.failures,
            stage_evidence.failures,
        ),
    )
```

Every exception class, including `FileExistsError`, reaches `_reprove_absent_install()`.
If the no-replace callable performs the real move and then raises, two-name reproof routes
the exact installed output through the same `failed-output` retention path. A true occupied
output leaves the exact stage and foreign output in separate current evidence for the outer
finalizer; it is not inferred from the exception class. If output identity cannot still be
proved, typed `NEEDS_CONTEXT` carries unknown/current output and stage evidence; neither the
expected object nor a concurrent replacement is deleted. Import `assert_never` and
`RetainedObjectInstalledContextError`, `merge_failures`, and `merge_retained` in this focused
module for the exhaustive secondary failure conversion above. A successful `failed-output`
retention mutates only the original typed error's live evidence and re-raises that same
instance; it never reconstructs the base class or assigns the error as its own cause.

- [ ] **Step 5: Make recovery retain the exact failed stage and replacement retain the exact previous generation**

Create `description_cache_publication_recovery_state.py` so a rollback failure is classified by the identities that exist *after* the failing operation, never by the identity that used to occupy a pathname. It scans the de-duplicated `recovery`/`stage` candidates through the held parent. A current `N` is normalized to `failed-stage`; a current `O` stays at an already-live retained record or moves to `recovery`; and every foreign but exact leaf also moves to `recovery` whenever that target is free. If a candidate already is the exact `failed-stage` or `recovery` leaf but its prior record was lost, construct and immediately re-prove the matching record instead of attempting a source-equals-target rename. Only an unreadable identity, occupied target, rejected atomic move, or lost parent binding remains transient. A final parent fsync covers the reverse exchange even when no candidate move was required; the durable retainer already synchronizes each move and moved-error outcome:

```python
"""Identity-aware evidence preservation after partial rollback."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_named_leaf import (
    read_named_leaf,
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_retention_names import RetainedCacheNames


type BoundRetain = Callable[
    [Path, DirectoryIdentity, RetainedCacheRole],
    RetainedCacheRecord,
]
type Sync = Callable[[int], None]


def normalize_recovery_failure(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    candidates: tuple[Path, ...],
    staged_identity: DirectoryIdentity,
    prior_records: tuple[RetainedCacheRecord, ...],
    prior_transient: tuple[PublicationTransientRecord, ...],
    prior_failures: tuple[Exception, ...],
    names: RetainedCacheNames,
    retain: BoundRetain,
    sync_parent: Sync,
) -> tuple[RetainedCacheRecord, ...]:
    """Preserve every exactly classified rollback leaf after a partial failure."""
    initial_proof = reprove_retained(
        parent_descriptor,
        parent,
        parent_identity,
        prior_records,
    )
    records = initial_proof.retained
    transient_proof = reprove_transient(
        parent_descriptor,
        parent,
        parent_identity,
        (*prior_transient, *initial_proof.transient),
    )
    transient = transient_proof.transient
    failures = merge_failures(
        prior_failures,
        (*initial_proof.failures, *transient_proof.failures),
    )
    for path in dict.fromkeys(candidates):
        if path.parent != parent:
            context_error = PublicationCommitContextError(
                "recovery candidate escaped the held parent; NEEDS_CONTEXT",
                records,
                transient,
                failures,
            )
            raise finalize_error_evidence(
                parent_descriptor,
                parent,
                parent_identity,
                context_error,
            )
        current_proof = read_named_leaf(parent_descriptor, path.name)
        failures = merge_failures(failures, current_proof.failures)
        if current_proof.readable and current_proof.identity is None:
            continue
        if current_proof.identity is None:
            transient = (
                *transient,
                PublicationTransientRecord(
                    parent,
                    path.name,
                    parent_identity,
                    None,
                ),
            )
            continue
        current = current_proof.identity
        role = (
            RetainedCacheRole.FAILED_STAGE
            if current == staged_identity
            else RetainedCacheRole.RECOVERY
        )
        existing = tuple(
            record
            for record in records
            if record.path == path
            and record.identity == current
            and (
                current != staged_identity
                or record.role is RetainedCacheRole.FAILED_STAGE
            )
        )
        if existing:
            continue
        target = names.path(role)
        try:
            retained = (
                RetainedCacheRecord(path, role, *current)
                if path == target
                else retain(path, current, role)
            )
        except DescriptionCachePublicationError as retention_error:
            raise finalize_error_evidence(
                parent_descriptor,
                parent,
                parent_identity,
                retention_error,
                earlier_retained=records,
                earlier_transient=transient,
                earlier_failures=failures,
            )
        retained_proof = reprove_retained(
            parent_descriptor,
            parent,
            parent_identity,
            merge_retained(records, (retained,)),
        )
        records = retained_proof.retained
        failures = merge_failures(failures, retained_proof.failures)
        transient = tuple(
            dict.fromkeys((*transient, *retained_proof.transient))
        )
    try:
        sync_parent(parent_descriptor)
    except Exception as sync_error:  # noqa: BROAD_EXCEPT_OK - rollback durability
        sync_proof = reprove_retained(
            parent_descriptor,
            parent,
            parent_identity,
            records,
        )
        context_error = PublicationCommitContextError(
            "partial rollback could not be durably synchronized; NEEDS_CONTEXT",
            sync_proof.retained,
            (*transient, *sync_proof.transient),
            failures=merge_failures(
                failures,
                (sync_error, *sync_proof.failures),
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
        raise finalized
    try:
        live = require_live_retained_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            records,
        )
    except DescriptionCachePublicationError as evidence_error:
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            evidence_error,
            earlier_transient=transient,
            earlier_failures=failures,
        )
    if transient:
        context_error = PublicationCommitContextError(
            "partial rollback needs exact operator context; NEEDS_CONTEXT",
            live,
            transient,
            failures,
        )
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
        )
    return live


__all__ = ("normalize_recovery_failure",)
```

Keep this module below 200 pure LOC. In `description_cache_publication_recovery.py`, replace `_remove_recovered_stage()` with `_retain_recovered_stage()`. Keep the exact reverse-exchange/validation sequence, track the current private candidate after every successful rename, validate `N`, and call the already durable bound retainer:

```python
_require_valid_identity(
    parent_descriptor,
    private,
    staged_identity,
    require_valid,
)
return retain(private, staged_identity, RetainedCacheRole.FAILED_STAGE)
```

Wrap the complete restore sequence in one error boundary. On any `DescriptionCachePublicationError` or `OSError`, first merge `prior_records` with the caught error's `retained` records and pass both `prior_transient` and the caught error's `transient` records through `reprove_transient()`. Then call `normalize_recovery_failure()` with `(private, recovery, stage)`, that merged current evidence, and the transaction's `names`. This explicitly preserves a `failed-stage` record when the final retain moved successfully and only its fsync/evidence step raised. The normalizer classifies every candidate by its *current* inode, performs its final synchronization, and raises `PublicationCommitContextError(f"{detail}; NEEDS_CONTEXT", live, freshly_reproved_transient)` from the original failure when it cannot return the exact recovered record. The caller never concatenates pre-exchange transient tuples and does not attempt a second pathname-based “retain previous identity” fallback: after reverse exchange, that pathname contains `N`, and the state module must classify it as `failed-stage`. `restore_previous_generation()` returns the exact `failed-stage` record only on a completely restored, validated, synchronized path.

The restore error boundary uses this exact evidence handoff:

```python
def _raise_normalized_recovery_error(
    caught: DescriptionCachePublicationError,
) -> Never:
    current_records = merge_retained(prior_records, caught.retained)
    current_evidence = reprove_transient(
        parent_descriptor,
        output.parent,
        parent_identity,
        (*prior_transient, *caught.transient),
    )
    try:
        live = normalize_recovery_failure(
            parent_descriptor,
            output.parent,
            parent_identity,
            (private, recovery, stage),
            staged_identity,
            current_records,
            current_evidence.transient,
            merge_failures(
                (*caught.failures, caught),
                current_evidence.failures,
            ),
            names,
            retain,
            sync_parent,
        )
    except DescriptionCachePublicationError as normalization_error:
        normalization_error.replace_failures(
            merge_failures(
                (*caught.failures, caught),
                normalization_error.failures,
            )
        )
        raise
    final_transient = reprove_transient(
        parent_descriptor,
        output.parent,
        parent_identity,
        current_evidence.transient,
    )
    raise PublicationCommitContextError(
        f"{detail}; NEEDS_CONTEXT",
        live,
        final_transient.transient,
        merge_failures(
            (*caught.failures, caught),
            (*current_evidence.failures, *final_transient.failures),
        ),
    ) from caught
```

The complete restore `try` calls this nested helper from
`except DescriptionCachePublicationError as caught`; its
`except Exception as caught:  # noqa: BROAD_EXCEPT_OK - recovery evidence boundary`
branch first wraps any remaining ordinary cause as a typed publication error with empty evidence and calls the same
helper. No old transient tuple is surfaced without the final current-name reproof.

Add four explicit RED variants to
`tests/test_description_cache_publication_recovery_durability.py`. Each first injects and
retains the exact original rollback exception object, then faults one distinct normalization
boundary: candidate retention, the normalizer's final parent sync, retained-evidence
reproof, or the final parent-binding proof performed by evidence finalization. Capture the
exact normalization exception object as well. Every variant requires the surfaced typed
error's `failures` ledger to contain the original object's pre-existing failures followed by
the original object, then the normalization object, all by identity and with no duplicate;
the final-parent variant also requires the finalizer's existing `__cause__` to remain that
parent-proof object. These tests must fail at their behavioral assertions before the catch
above exists, never during import or collection.

Confirm the initial Task 1 RED suite already contains parameterized cases in `tests/test_description_cache_publication_recovery_durability.py` for a fault immediately after reverse exchange, each post-exchange identity proof, parent sync, restored-output validation, recovered-stage validation, recovery→stage rename, its sync, and final retained-stage proof. For every post-exchange fault, require `output=O`, one live `failed-stage=N`, zero stale `recovery=O` records, and every surfaced record passing no-follow `stat`. Add an explicit stale-transient regression: seed `backup=O` transient evidence, let reverse exchange consume/reassign that name, fail at the next boundary, and require the caller to receive either the name's current inode or no backup record at all—never the old `(backup, O)` pair. Add a final-retain regression where `N` reaches `failed-stage` and the following fsync raises; the caught error's live record must survive recovery normalization. The same initial suite contains pre-exchange failures requiring `output=N` plus live `recovery=O`, a partial-rename case that locates `N` by current inode rather than the old variable name, a foreign exact candidate moved to free `recovery`, and an already-named `recovery` candidate re-recorded without a source-equals-target rename. Run this file and record the expected behavioral failures before creating the state module. No test uses sleeps or a fake filesystem.

In `description_cache_publication_commit.py`, replace backup removal with the existing exact rollback boundary followed by a non-destructive commit. Catch `RetainedObjectInstalledContextError` first and propagate it without any rollback attempt: its intended `previous` target is the irreversible namespace commit point even if durability or caller-visible evidence is uncertain. Only a generic retention error that never observed the intended role may enter rollback. Such an error cannot assume that `backup` still exists because collision fallback may have moved the exact old inode to the same transaction's `recovery` path. Build candidates from `backup` plus error records whose identity equals `backup_identity`, call `select_live_identity_path()` to require exactly one descriptor-proved source, and pass that path plus `names` and the current prior records to `restore_previous_generation()`. After a successful restore, call `reprove_retained()` before replacing consumed recovery evidence with the returned live `failed-stage` record, and rebuild transient evidence from current names rather than clearing or concatenating old tuples. If restoration fails, its recovery boundary already contains the original error's freshly re-proved filesystem evidence; add the original retention error and its ordered failures to the restoration error's typed failure ledger, then propagate the restoration error without a new `from` clause so its existing cause is not overwritten. No CLI/error record may point at a path that rollback consumed. On success the bound retainer has already synchronized the parent, so commit performs no duplicate fsync; it returns a `DescriptionCachePublicationProof` whose `RetainedCacheExpectation` binds the live `previous` record to the exact `previous_verified` bytes captured before exchange. Import `merge_failures` beside `merge_retained` in the commit module.

```python
try:
    retained = retain(
        backup,
        backup_identity,
        RetainedCacheRole.PREVIOUS,
    )
except RetainedObjectInstalledContextError:
    raise
except DescriptionCachePublicationError as retention_error:
    try:
        rollback_source = select_live_identity_path(
            parent_descriptor,
            output.parent,
            parent_identity,
            (
                backup,
                *(
                    record.path
                    for record in retention_error.retained
                    if record.identity == backup_identity
                ),
            ),
            backup_identity,
            retention_error.retained,
            retention_error.transient,
        )
        recovered = restore_previous_generation(
            parent_descriptor,
            parent_identity,
            output,
            output_identity,
            rollback_source,
            backup_identity,
            stage,
            names,
            rename_exchange,
            rename_noreplace,
            require_valid,
            retain,
            sync_parent,
            retention_error.retained,
            retention_error.transient,
            f"previous-generation retention failed: {retention_error}",
        )
    except PublicationCommitContextError as restoration_error:
        restoration_error.replace_failures(
            merge_failures(
                (*retention_error.failures, retention_error),
                restoration_error.failures,
            )
        )
        raise
    rollback_proof = reprove_retained(
        parent_descriptor,
        output.parent,
        parent_identity,
        retention_error.retained,
    )
    retention_error.replace_retained(
        merge_retained(
            rollback_proof.retained,
            (recovered,),
        )
    )
    rollback_transient = reprove_transient(
        parent_descriptor,
        output.parent,
        parent_identity,
        (*retention_error.transient, *rollback_proof.transient),
    )
    retention_error.replace_transient(rollback_transient.transient)
    retention_error.replace_failures(
        merge_failures(
            retention_error.failures,
            (*rollback_proof.failures, *rollback_transient.failures),
        )
    )
    raise

# `retain` is the already durable bound adapter. Do not fsync a second time here.
live_proof = reprove_retained(
    parent_descriptor,
    output.parent,
    parent_identity,
    (retained,),
)
if (
    live_proof.retained != (retained,)
    or live_proof.transient
    or live_proof.failures
):
    raise PublicationCommitContextError(
        "retained previous generation cannot be re-proved; NEEDS_CONTEXT",
        live_proof.retained,
        live_proof.transient,
        live_proof.failures,
    )
live = live_proof.retained
expectation = RetainedCacheExpectation(live[0], previous_verified)
return DescriptionCachePublicationProof(
    DescriptionCachePublicationResult(verified, live),
    (expectation,),
)
```

Update `description_cache_publication_replacement.py` without adding a new responsibility: remove the remover argument, thread `names` and `retain` through `_restore()` and `commit_replacement()`, and carry `previous_verified` from the pre-exchange output validation. `_restore()` now returns the live `failed-stage` record from `restore_previous_generation()`; every caller that successfully restores raises `DescriptionCachePublicationError(str(cause), (recovered,)) from cause` instead of re-raising an unannotated `OSError`. A restoration failure propagates its already-normalized `PublicationCommitContextError`. After exchange, require the new output validation to equal `stage_verified` and the displaced/backup validation to equal `previous_verified`; a self-consistent stage substitution therefore cannot be published. The exact post-exchange comparisons are:

```python
verified = require_valid(output)
if verified != stage_verified:
    raise DescriptionCachePublicationError(
        "published replacement differs from the descriptor-verified stage"
    )
displaced = require_valid(stage)
if displaced != previous_verified:
    raise DescriptionCachePublicationError(
        "displaced generation differs from the pre-exchange output"
    )
```

After `stage -> backup`, repeat the `previous_verified` equality check on `backup` before commit. Move any new helper into commit/recovery/retention modules so replacement stays at or below its current pure LOC.

- [ ] **Step 6: Hold the exact stage across build, normalize creation failures, and retain final evidence**

Confirm the initial Task 1 RED files already contain four capture/durability cases: generic identity after directory-capture failure moves to `recovery`; a proved directory followed by initial parent-fsync failure moves to `failed-stage`; an occupied recovery target or filesystem no-replace rejection leaves one typed transient; and a post-retain sync failure still carries every live record. Confirm the race file already contains deterministic parent-path and stage-leaf takeovers after capture but before the first write. Both takeover tests call the real builder after the rename, require the foreign sentinel tree to contain no cache payload or modified byte, and require typed `NEEDS_CONTEXT`. The leaf-takeover error records distinct current-leaf and held-stage identities.

Confirm the initial Task 1 RED suite already contains `tests/test_description_cache_publication_stage_io.py` with three behavioral cases. The first wraps the current publish dispatch, replaces all five just-written leaves with a different self-consistent valid cache before current self-validation, and requires publication to reject rather than publish the substitute. The second replaces one leaf immediately after its writer returns and before held-stage reading and must fail on device/inode/size/mtime/ctime/mode/SHA-256 mismatch once the proof API is implemented. The third lets descriptor validation of stage A finish, replaces all five leaves with self-consistent stage B before the first atomic rename, and requires the transaction's second complete held-stage reread to reject it before any output rename; the foreign/current stage is normalized as evidence, and the original output remains unchanged. Add a fourth case that mutates the first file in place after it is read and before the fifth file is read while preserving directory inode and byte length; whole-generation post-snapshot/hash proof must reject it. The initial RED imports only currently available publication/loader namespaces and fails at the observable assertion, not collection; after `TrustedCacheLeafProof` exists, refactor imports without changing the scenarios. Use real descriptor-relative rename/write operations and no sleeps. Run this file in the exact Task 1 Step 2 gate and record the expected behavioral failures before any stage-I/O/loader production edit.

Create `w3xtool/description_cache_publication_descriptor_close.py` before adding the bound
context manager. It is the only descriptor-close boundary. The mutable ledger exists solely
to remember the last immutable evidence proven on a nominal success path; its documented
mutation is not domain-state mutation. Every close callable is attempted, and close failure
handling performs no further filesystem proof:

```python
"""Typed close boundary for publication-owned descriptors."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
)


type CloseDescriptor = Callable[[int], None]
type NamedDescriptor = tuple[str, int]


@dataclass(slots=True)  # noqa: MUTABLE_OK - resource owner records final proof
class DescriptorCloseLedger:
    """Last immutable evidence available if close fails after success."""

    retained: tuple[RetainedCacheRecord, ...] = ()
    transient: tuple[PublicationTransientRecord, ...] = ()

    def remember(
        self,
        retained: tuple[RetainedCacheRecord, ...],
        transient: tuple[PublicationTransientRecord, ...],
    ) -> None:
        self.retained = retained
        self.transient = transient


def close_publication_descriptors(
    descriptors: tuple[NamedDescriptor, ...],
    in_flight: BaseException | None,
    ledger: DescriptorCloseLedger,
    close_descriptor: CloseDescriptor = os.close,
) -> None:
    """Attempt every close without replacing an in-flight typed failure."""
    failures: list[tuple[str, Exception]] = []
    def attempt(index: int) -> None:
        if index == len(descriptors):
            return
        label, descriptor = descriptors[index]
        try:
            close_descriptor(descriptor)
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK - descriptor close evidence
            failures.append((label, exc))
        finally:
            attempt(index + 1)

    attempt(0)
    if not failures:
        return
    detail = "descriptor close failed: " + ", ".join(
        f"{label}={type(cause).__name__}" for label, cause in failures
    )
    failure_objects = tuple(cause for _, cause in failures)
    match in_flight:
        case DescriptionCachePublicationError() as publication_error:
            publication_error.append_close_context(detail, failure_objects)
        case None:
            raise PublicationCommitContextError(
                f"{detail}; NEEDS_CONTEXT",
                ledger.retained,
                ledger.transient,
                failure_objects,
            ) from failures[0][1]
        case BaseException() as active_error:
            active_error.add_note(detail)
        case unreachable:
            assert_never(unreachable)


__all__ = (
    "DescriptorCloseLedger",
    "close_publication_descriptors",
)
```

The error base's `append_close_context()` is the only mutation used for an in-flight typed
error and leaves `retained`, `transient`, and the existing cause untouched while identity-
merging every close exception after the existing ledger. Unit tests call
`close_publication_descriptors()` with an injected callable; lifecycle tests exercise the
same helper through the bound resource. Add this function to the explicit broad-catch allow
list and require both descriptor labels in the injected call log even when both close calls
raise.

Replace pathname `stage.mkdir()` plus later reopen with an owned descriptor context in
`description_cache_publication_stage.py`. This improves all behavior after capture but does
not bind creation provenance across `mkdirat` return and the first stage open: POSIX exposes
no descriptor-returning directory-creation primitive here, and the initial named proof plus
descriptor equality must not be described as closing that window. Under the explicit
no-replacement precondition, the equality check still detects a change between the first
proof and descriptor capture. Add `assert_never` and `merge_failures` to this module's
focused imports; the post-collision match below is exhaustive and its finalized wrapper
stores the ordinary failure instead of replacing any cause created during evidence
finalization:

```python
@dataclass(frozen=True, slots=True)
class BoundDescriptionCacheStage:
    """The exact parent and captured stage held for one publication attempt."""

    parent_descriptor: int
    stage_descriptor: int
    stage: Path
    parent_identity: DirectoryIdentity
    stage_identity: DirectoryIdentity
    close_ledger: DescriptorCloseLedger

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        close_publication_descriptors(
            (
                ("stage", self.stage_descriptor),
                ("parent", self.parent_descriptor),
            ),
            _exception,
            self.close_ledger,
        )


def descriptor_identity(descriptor: int) -> DirectoryIdentity:
    """Return the exact directory identity held by one descriptor."""
    details = os.fstat(descriptor)
    if not stat.S_ISDIR(details.st_mode):
        raise PublicationCommitContextError(
            "publication descriptor is not a directory; NEEDS_CONTEXT"
        )
    return details.st_dev, details.st_ino


def create_stage_and_capture(
    stage: Path,
    output: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> BoundDescriptionCacheStage:
    """Create, capture, synchronize, and return one private stage."""
    try:
        parent_descriptor = os.open(stage.parent, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise PublicationCommitContextError(
            "cannot bind publication parent before stage creation; NEEDS_CONTEXT",
            failures=(exc,),
        ) from exc
    stage_descriptor = -1
    parent_identity: DirectoryIdentity | None = None
    directory_expected: DirectoryIdentity | None = None
    held_expected: DirectoryIdentity | None = None
    created = False
    collision_handled = False
    transferred = False
    try:
        parent_identity = parent_descriptor_identity(parent_descriptor)
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        try:
            os.mkdir(stage.name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError as exc:
            collision_handled = True
            collision_evidence = capture_transient_record(
                parent_descriptor,
                stage,
                parent_identity,
                None,
            )
            collision_error = DescriptionCacheConcurrentDestinationError(
                "private stage name was acquired concurrently",
                transient=collision_evidence.transient,
                failures=merge_failures(
                    (exc,), collision_evidence.failures
                ),
            )
            finalized = finalize_error_evidence(
                parent_descriptor,
                stage.parent,
                parent_identity,
                collision_error,
                parent_loss_evidence=capture_named_transient(
                    parent_descriptor,
                    stage.parent,
                    parent_identity,
                    output,
                ),
            )
            raise finalized
        created = True
        directory_expected = directory_identity(parent_descriptor, stage.name)
        stage_descriptor = os.open(
            stage.name,
            _DIRECTORY_FLAGS,
            dir_fd=parent_descriptor,
        )
        held_expected = descriptor_identity(stage_descriptor)
        if held_expected != directory_expected:
            raise PublicationCommitContextError(
                "stage leaf changed between first proof and descriptor capture; "
                "NEEDS_CONTEXT"
            )
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        sync_parent(parent_descriptor)
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
        bound = BoundDescriptionCacheStage(
            parent_descriptor,
            stage_descriptor,
            stage,
            parent_identity,
            directory_expected,
            DescriptorCloseLedger(),
        )
        transferred = True
        return bound
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - created-stage normalization
        if collision_handled:
            match exc:
                case DescriptionCachePublicationError():
                    raise
                case Exception() as ordinary_error:
                    pass
                case unreachable:
                    assert_never(unreachable)
            if parent_identity is None:
                raise PublicationCommitContextError(
                    "stage collision lost its parent identity; NEEDS_CONTEXT"
                ) from ordinary_error
            collision_failure = PublicationCommitContextError(
                "stage-collision evidence raised an ordinary exception; "
                "NEEDS_CONTEXT",
                failures=(ordinary_error,),
            )
            finalized = finalize_error_evidence(
                parent_descriptor,
                stage.parent,
                parent_identity,
                collision_failure,
                parent_loss_evidence=capture_named_transient(
                    parent_descriptor,
                    stage.parent,
                    parent_identity,
                    output,
                ),
            )
            finalized.replace_failures(
                merge_failures(finalized.failures, (ordinary_error,))
            )
            raise finalized
        if parent_identity is None:
            match exc:
                case DescriptionCachePublicationError():
                    raise
                case Exception() as ordinary_error:
                    context_error = PublicationCommitContextError(
                        "stage parent identity is unavailable; NEEDS_CONTEXT",
                        failures=(ordinary_error,),
                    )
                case unreachable:
                    assert_never(unreachable)
            raise context_error from ordinary_error
        if not created:
            match exc:
                case DescriptionCachePublicationError() as publication_error:
                    creation_error = publication_error
                case Exception() as ordinary_error:
                    creation_error = PublicationCommitContextError(
                        "stage creation could not start safely; NEEDS_CONTEXT",
                        failures=(ordinary_error,),
                    )
                case unreachable:
                    assert_never(unreachable)
            finalized = finalize_error_evidence(
                parent_descriptor,
                stage.parent,
                parent_identity,
                creation_error,
                parent_loss_evidence=capture_named_transient(
                    parent_descriptor,
                    stage.parent,
                    parent_identity,
                    output,
                ),
            )
            raise finalized
        raise_normalized_stage_creation_failure(
            parent_descriptor,
            stage,
            output,
            parent_identity,
            directory_expected,
            held_expected,
            names,
            rename_noreplace,
            sync_parent,
            exc,
        )
    finally:
        if not transferred:
            descriptors = (
                (
                    ("stage", stage_descriptor),
                    ("parent", parent_descriptor),
                )
                if stage_descriptor >= 0
                else (("parent", parent_descriptor),)
            )
            close_publication_descriptors(
                descriptors,
                sys.exception(),
                DescriptorCloseLedger(),
            )
```

The `parent_identity is None` branch bare-re-raises a caught typed publication error, so an
initial descriptor-`fstat` wrapper retains its exact low-level ledger and cause. The
`created is False` branch passes a caught typed publication error itself to
`finalize_error_evidence()`; it never substitutes that aggregate object for the underlying
entries in `failures`, and the finalized result is raised without a new `from` clause. Only
the ordinary-exception match arms construct a new wrapper seeded with the ordinary object.

The nested `FileExistsError` handler surrounds only `os.mkdir()`. Its boolean marker lets
the already-finalized typed collision pass through the outer evidence boundary with bare
`raise`; the outer boundary never executes `raise exc from exc`. From
the first instruction after a successful `mkdir()` onward, every exception class—including
another `FileExistsError`—observes `created=True` and calls
`raise_normalized_stage_creation_failure()` before either descriptor closes.

The return transfers both descriptors to `BoundDescriptionCacheStage`; the `transferred`
flag makes the `finally` block call the same typed close boundary only on creation failure.
Import `sys`, `DescriptorCloseLedger`, and `close_publication_descriptors` in the stage
resource module. `sys.exception()` passes the already-normalized in-flight error into cleanup,
so a close failure can append context but cannot replace that error. Put
`raise_normalized_stage_creation_failure(...) -> Never` and
`capture_transient_record(...)` in the new focused normalization module so the stage resource
module stays below 200 pure LOC. The failure boundary first re-proves the public parent
binding, then captures the current leaf with `read_named_leaf()`. If the parent is unbound or
the current identity is unavailable, it raises `PublicationCommitContextError` with
`capture_transient_record(...)`. Otherwise it selects `FAILED_STAGE` only when
`directory_expected` equals the current identity and selects `RECOVERY` for every
generic/changed identity, then calls the mandatory `retain_durably()` adapter while the
parent descriptor is still open. Import that adapter from
`description_cache_publication_retention_durability.py`; this lifecycle module must not
import raw `retain_object()`. The adapter owns both success/error synchronization and
live-record proof, so this helper performs no second post-retain fsync. If the opened stage
descriptor and named leaf had different identities, it also carries a transient for the
still-held but no-longer-locatable directory. If retention itself cannot normalize the name,
it appends the distinct held-stage evidence before re-raising. This helper never deletes,
follows, or reopens a pathname.

```python
def raise_normalized_stage_creation_failure(
    parent_descriptor: int,
    stage: Path,
    output: Path,
    parent_identity: DirectoryIdentity,
    directory_expected: DirectoryIdentity | None,
    held_identity: DirectoryIdentity | None,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
    cause: Exception,
) -> Never:
    initiating_failures = (cause,)
    try:
        require_parent_identity(parent_descriptor, stage.parent, parent_identity)
    except PublicationCommitContextError as parent_error:
        stage_evidence = capture_transient_record(
            parent_descriptor,
            stage,
            parent_identity,
            held_identity,
        )
        context_error = PublicationCommitContextError(
            "stage parent lost its captured binding; NEEDS_CONTEXT",
            transient=stage_evidence.transient,
            failures=merge_failures(
                merge_failures(
                    initiating_failures,
                    (*parent_error.failures, parent_error),
                ),
                stage_evidence.failures,
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            stage.parent,
            parent_identity,
            context_error,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                stage.parent,
                parent_identity,
                output,
            ),
        )
        raise finalized
    current_proof = read_named_leaf(parent_descriptor, stage.name)
    if current_proof.identity is None:
        stage_evidence = capture_transient_record(
            parent_descriptor,
            stage,
            parent_identity,
            held_identity,
        )
        context_error = PublicationCommitContextError(
            "created stage identity is unavailable; NEEDS_CONTEXT",
            transient=stage_evidence.transient,
            failures=merge_failures(
                merge_failures(
                    initiating_failures,
                    current_proof.failures,
                ),
                stage_evidence.failures,
            ),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            stage.parent,
            parent_identity,
            context_error,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                stage.parent,
                parent_identity,
                output,
            ),
        )
        raise finalized
    current = current_proof.identity
    role = (
        RetainedCacheRole.FAILED_STAGE
        if directory_expected == current
        else RetainedCacheRole.RECOVERY
    )
    held_transient = (
        ()
        if held_identity is None or held_identity == current
        else (
            PublicationTransientRecord(
                stage.parent,
                stage.name,
                parent_identity,
                None,
                held_identity,
            ),
        )
    )
    try:
        retained = retain_durably(
            parent_descriptor,
            stage.parent,
            parent_identity,
            stage,
            current,
            names,
            role,
            rename_noreplace,
            sync_parent,
        )
    except DescriptionCachePublicationError as retention_error:
        retention_error.replace_failures(
            merge_failures(initiating_failures, retention_error.failures)
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            stage.parent,
            parent_identity,
            retention_error,
            later_transient=held_transient,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                stage.parent,
                parent_identity,
                output,
            ),
        )
        raise finalized
    context_error = PublicationCommitContextError(
        "stage creation failed after evidence normalization; NEEDS_CONTEXT",
        (retained,),
        held_transient,
        initiating_failures,
    )
    finalized = finalize_error_evidence(
        parent_descriptor,
        stage.parent,
        parent_identity,
        context_error,
        parent_loss_evidence=capture_named_transient(
            parent_descriptor,
            stage.parent,
            parent_identity,
            output,
        ),
    )
    raise finalized
```

`capture_transient_record()` always reads the named leaf relative to the held parent and
separately accepts the held stage identity. It returns rows and the exact non-absence read
fault together:

```python
def capture_transient_record(
    parent_descriptor: int,
    stage: Path,
    parent_identity: DirectoryIdentity,
    held_identity: DirectoryIdentity | None,
) -> RetainedEvidenceReproof:
    proof = read_named_leaf(parent_descriptor, stage.name)
    if proof.readable and proof.identity is None and held_identity is None:
        return RetainedEvidenceReproof()
    return RetainedEvidenceReproof(
        transient=(
            PublicationTransientRecord(
                stage.parent,
                stage.name,
                parent_identity,
                proof.identity,
                held_identity,
            ),
        ),
        failures=proof.failures,
    )
```

Import `read_named_leaf` from `description_cache_publication_named_leaf.py` and
`RetainedEvidenceReproof` from the model module. A readable `FileNotFoundError` with no held
identity returns empty evidence; any other `OSError` returns `identity=None` plus that exact
object.

The top-level publisher calls the complete support preflight first, allocates exactly one transaction ID, and enters `with create_stage_and_capture(...) as bound:`. No code calls `Path.mkdir()`, reopens the publication parent, or closes either descriptor before final result/error evidence is assembled.

Create `description_cache_publication_stage_finalization.py` with
`finalize_private_artifacts()` and its focused `retain_stage()` helper. It borrows the
still-open bound descriptors and never resolves or reopens `stage.parent`. It attempts
backup normalization and stage normalization independently so one failure cannot hide the
other. An exact unexpected backup moves durably to `recovery`; an exact held stage moves
durably to `failed-stage`; and every foreign-stage return or failure goes through the full
location proof below before evidence escapes. Import `locate_consumed_stage` from the
separate focused `description_cache_publication_stage_location.py`; the locator definition
shown below belongs to that file. The locator imports `assert_never`, the bound-stage type,
`capture_transient_record`, `read_named_leaf`, `finalize_error_evidence`,
`reprove_retained`, `reprove_transient`, `merge_failures`, `merge_retained`,
`object_identity`, `DirectoryIdentity`, `RetainedEvidenceReproof`, and the other model/name
types shown by its signature. It imports `_snapshot_failures` with the immutable scan
helpers from `description_cache_publication_stage_location_scan.py`. The finalization
module imports only its stage-retention dependencies plus the three focused orchestration
contracts introduced below; no lifecycle module imports raw `retain_object()`.

```python
def retain_stage(
    bound: BoundDescriptionCacheStage,
    output: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
    known_retained: tuple[RetainedCacheRecord, ...],
    known_transient: tuple[PublicationTransientRecord, ...],
) -> RetainedCacheRecord | None:
    try:
        require_parent_identity(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
        )
    except PublicationCommitContextError as context_error:
        bound_evidence = _bound_evidence(bound)
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=merge_retained(
                known_retained,
                context_error.retained,
            ),
            known_transient=(
                *known_transient,
                *context_error.transient,
                *bound_evidence.transient,
            ),
            prior_failures=merge_failures(
                (*context_error.failures, context_error),
                bound_evidence.failures,
            ),
            detail="publication parent changed during final stage proof",
        )
    stage_proof = read_named_leaf(
        bound.parent_descriptor,
        bound.stage.name,
    )
    if stage_proof.readable and stage_proof.identity is None:
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
        )
    if stage_proof.identity is None:
        bound_evidence = _bound_evidence(bound)
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=(
                *known_transient,
                *bound_evidence.transient,
            ),
            prior_failures=merge_failures(
                stage_proof.failures,
                bound_evidence.failures,
            ),
            detail="cannot prove final stage retention",
        )
    identity = stage_proof.identity
    if identity != bound.stage_identity:
        try:
            recovery = retain_durably(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
                bound.stage,
                identity,
                names,
                RetainedCacheRole.RECOVERY,
                rename_noreplace,
                sync_parent,
            )
        except DescriptionCachePublicationError as retention_error:
            return locate_consumed_stage(
                bound,
                output,
                names,
                known_retained=known_retained,
                known_transient=known_transient,
                later_retained=retention_error.retained,
                later_transient=retention_error.transient,
                prior_failures=(
                    *retention_error.failures,
                    retention_error,
                ),
                detail="foreign final-stage retention failed",
            )
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
            later_retained=(recovery,),
            detail="final stage leaf no longer names the held stage",
        )
    try:
        return retain_durably(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            bound.stage,
            bound.stage_identity,
            names,
            RetainedCacheRole.FAILED_STAGE,
            rename_noreplace,
            sync_parent,
        )
    except DescriptionCachePublicationError as retention_error:
        return locate_consumed_stage(
            bound,
            output,
            names,
            known_retained=known_retained,
            known_transient=known_transient,
            later_retained=retention_error.retained,
            later_transient=retention_error.transient,
            prior_failures=(
                *retention_error.failures,
                retention_error,
            ),
            detail="failed-stage retention did not complete cleanly",
        )


def _bound_evidence(
    bound: BoundDescriptionCacheStage,
) -> RetainedEvidenceReproof:
    return capture_transient_record(
        bound.parent_descriptor,
        bound.stage,
        bound.parent_identity,
        bound.stage_identity,
    )
```

Create `description_cache_publication_stage_location.py` with the locator below. It is the
only module that searches the transaction's legal names for the still-open held stage. It
always snapshots output first and then `previous`, `failed-stage`, `failed-output`, and
`recovery`, repeats that complete ordered snapshot, and rejects any change. `known_retained`
identifies already published non-held objects; it never makes their inode a held-stage
match and never blocks a clean unique held match. `later_retained` holds evidence created by
the current private attempt. `detail` forces a typed error after a preceding abnormal action,
but still uses the same two-round location proof. Every caller passes exact parent-proof,
stage-read, or foreign/held-stage retention faults through `prior_failures`; the locator
then appends retained/transient reproof failures, first-snapshot failures,
second-snapshot failures, and any final held-capture failure in observation order with
`merge_failures()`. Import the immutable scan helpers from
`description_cache_publication_stage_location_scan.py` and import
`require_parent_identity`; a clean result performs no filesystem operation after that final
parent-binding proof:

```python
def locate_consumed_stage(
    bound: BoundDescriptionCacheStage,
    output: Path,
    names: RetainedCacheNames,
    *,
    known_retained: tuple[RetainedCacheRecord, ...] = (),
    known_transient: tuple[PublicationTransientRecord, ...] = (),
    prior_failures: tuple[Exception, ...] = (),
    later_retained: tuple[RetainedCacheRecord, ...] = (),
    later_transient: tuple[PublicationTransientRecord, ...] = (),
    detail: str | None = None,
) -> RetainedCacheRecord | None:
    expected_records = merge_retained(known_retained, later_retained)
    prior = reprove_retained(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        expected_records,
    )
    retained = prior.retained
    transient_proof = reprove_transient(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        (
            *known_transient,
            *later_transient,
            *prior.transient,
        ),
    )
    transient = transient_proof.transient
    before = _snapshot_locations(bound, output, names)
    after = _snapshot_locations(bound, output, names)
    failures = merge_failures(prior_failures, prior.failures)
    failures = merge_failures(failures, transient_proof.failures)
    failures = merge_failures(failures, _snapshot_failures(before))
    failures = merge_failures(failures, _snapshot_failures(after))
    locations_changed = before != after
    matches = tuple(
        state
        for state in after
        if state.readable and state.identity == bound.stage_identity
    )
    foreign = tuple(
        _state_transient(bound, state)
        for state in after
        if (
            not state.readable
            or (
                state.identity is not None
                and state.identity != bound.stage_identity
                and not _is_known_state(state, retained)
            )
        )
    )
    matching_records = tuple(
        record
        for state in matches
        if (record := _retained_match(state)) is not None
    )
    held_record = (
        _retained_match(matches[0]) if len(matches) == 1 else None
    )
    clean = bool(
        detail is None
        and not locations_changed
        and prior.retained == expected_records
        and _known_records_match(after, retained)
        and len(matches) == 1
        and not transient
        and not foreign
        and not failures
    )
    if clean:
        try:
            require_parent_identity(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
            )
        except PublicationCommitContextError as parent_error:
            context_error = PublicationCommitContextError(
                "publication parent changed after final stage-location scan; "
                "NEEDS_CONTEXT",
                transient=_snapshot_as_transient(bound, after),
                failures=merge_failures(
                    failures,
                    (*parent_error.failures, parent_error),
                ),
            )
            raise context_error from parent_error
        return held_record

    output_held_identity = (
        bound.stage_identity
        if len(matches) == 1 and matches[0].path == output
        else None
    )
    output_probe = PublicationTransientRecord(
        bound.stage.parent,
        output.name,
        bound.parent_identity,
        after[0].identity,
        output_held_identity,
    )
    missing_held_evidence = (
        RetainedEvidenceReproof()
        if len(matches) == 1
        else capture_transient_record(
            bound.parent_descriptor,
            bound.stage,
            bound.parent_identity,
            bound.stage_identity,
        )
    )
    failures = merge_failures(failures, missing_held_evidence.failures)
    if locations_changed:
        reason = "stage-location names changed between complete scans"
    elif (
        prior.retained != expected_records
        or not _known_records_match(after, retained)
    ):
        reason = "known retained evidence changed during stage-location proof"
    elif len(matches) != 1:
        reason = "absent stage leaf does not uniquely locate the held stage"
    elif transient or foreign:
        reason = "stage-location set contains unrelated current evidence"
    else:
        reason = "stage-location proof followed an earlier failure"
    context_error = PublicationCommitContextError(
        (
            f"{reason}; NEEDS_CONTEXT"
            if detail is None
            else f"{detail}; {reason}; NEEDS_CONTEXT"
        ),
        merge_retained(retained, matching_records),
        tuple(
            dict.fromkeys(
                (
                    *transient,
                    *foreign,
                    output_probe,
                    *missing_held_evidence.transient,
                )
            )
        ),
        failures,
    )
    finalized = finalize_error_evidence(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        context_error,
    )
    raise finalized
```

Create `description_cache_publication_stage_location_scan.py` for the fixed ordered
snapshot and pure state/evidence conversions imported by the locator. The scan module does
not import the locator or finalizer. It imports `read_named_leaf` and `merge_failures`; every
state retains its exact non-absence read fault until the locator consumes
`_snapshot_failures()`:

```python
@dataclass(frozen=True, slots=True)
class _StageLocationState:
    path: Path
    role: RetainedCacheRole | None
    readable: bool
    identity: DirectoryIdentity | None
    failure: OSError | None


def _snapshot_locations(
    bound: BoundDescriptionCacheStage,
    output: Path,
    names: RetainedCacheNames,
) -> tuple[_StageLocationState, ...]:
    states: list[_StageLocationState] = []
    for path, role in (
        (output, None),
        (
            names.path(RetainedCacheRole.PREVIOUS),
            RetainedCacheRole.PREVIOUS,
        ),
        (
            names.path(RetainedCacheRole.FAILED_STAGE),
            RetainedCacheRole.FAILED_STAGE,
        ),
        (
            names.path(RetainedCacheRole.FAILED_OUTPUT),
            RetainedCacheRole.FAILED_OUTPUT,
        ),
        (
            names.path(RetainedCacheRole.RECOVERY),
            RetainedCacheRole.RECOVERY,
        ),
    ):
        proof = read_named_leaf(bound.parent_descriptor, path.name)
        states.append(
            _StageLocationState(
                path,
                role,
                proof.readable,
                proof.identity,
                proof.failure,
            )
        )
    return tuple(states)


def _snapshot_failures(
    states: tuple[_StageLocationState, ...],
) -> tuple[Exception, ...]:
    failures: tuple[Exception, ...] = ()
    for state in states:
        if state.failure is not None:
            failures = merge_failures(failures, (state.failure,))
    return failures


def _retained_match(
    state: _StageLocationState,
) -> RetainedCacheRecord | None:
    match state.role:
        case None:
            return None
        case RetainedCacheRole() as role:
            if state.identity is None:
                return None
            return RetainedCacheRecord(state.path, role, *state.identity)
        case unreachable:
            assert_never(unreachable)


def _is_known_state(
    state: _StageLocationState,
    records: tuple[RetainedCacheRecord, ...],
) -> bool:
    return any(
        record.path == state.path and record.identity == state.identity
        for record in records
    )


def _known_records_match(
    states: tuple[_StageLocationState, ...],
    records: tuple[RetainedCacheRecord, ...],
) -> bool:
    return all(
        any(
            state.readable
            and state.path == record.path
            and state.identity == record.identity
            for state in states
        )
        for record in records
    )


def _state_transient(
    bound: BoundDescriptionCacheStage,
    state: _StageLocationState,
) -> PublicationTransientRecord:
    return PublicationTransientRecord(
        bound.stage.parent,
        state.path.name,
        bound.parent_identity,
        state.identity,
    )


def _snapshot_as_transient(
    bound: BoundDescriptionCacheStage,
    states: tuple[_StageLocationState, ...],
) -> tuple[PublicationTransientRecord, ...]:
    return tuple(
        PublicationTransientRecord(
            bound.stage.parent,
            state.path.name,
            bound.parent_identity,
            state.identity,
            (
                bound.stage_identity
                if state.identity == bound.stage_identity
                else None
            ),
        )
        for state in states
        if not state.readable or state.identity is not None
    )
```

A clean unique match returns only the held-stage location: `None` means exact at output and
a record means exact at one legal retained leaf. Any forced/other evidence produces a typed
error. Known `previous=old` remains separate from the held-match set and does not block a
clean `output=new` conclusion. The error path always seeds an output probe so
`finalize_error_evidence()` re-reads output even when its terminal snapshot was absent, but
that probe carries `held_identity` only when output itself is the unique held match. The
distinct held-stage transient is appended only when `len(matches) != 1`. Consequently
`stage=F, output=N` first preserves `F`, then reports the terminal `output=N` plus the
preserved `F` without falsely claiming that held `N` is missing. A held identity at
`previous` is found by the same scan and never creates a second held-output claim. A unique held record plus a different foreign name
likewise reports the foreign name separately and never appends a contradictory held
transient. If the clean-path parent binding fails, `_snapshot_as_transient()` demotes the
already captured set and raises without another filesystem read.

Back in `description_cache_publication_stage_finalization.py`, add only the two-attempt
orchestrator. Import `attempt_private` and `record_tuple` from
`description_cache_publication_private_attempt.py`, and import `retain_backup` from
`description_cache_publication_backup_finalization.py`. Also import `assert_never` and
`merge_failures`. Evidence produced by the backup attempt is part of the stage locator's
known set before the stage attempt starts; the same recovery path/inode can therefore never
be emitted once as retained and again as an unrelated transient:

```python


def finalize_private_artifacts(
    bound: BoundDescriptionCacheStage,
    backup: Path,
    output: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
    known_retained: tuple[RetainedCacheRecord, ...] = (),
    known_transient: tuple[PublicationTransientRecord, ...] = (),
) -> tuple[RetainedCacheRecord, ...]:
    """Attempt both private leaves and return only live normalized records."""
    backup_attempt = attempt_private(
        bound,
        backup,
        None,
        lambda: retain_backup(
            bound,
            backup,
            names,
            rename_noreplace,
            sync_parent,
        )
    )
    stage_known_retained = merge_retained(
        known_retained,
        record_tuple(backup_attempt.record),
    )
    stage_known_transient = known_transient
    match backup_attempt.error:
        case None:
            pass
        case DescriptionCachePublicationError() as backup_error:
            stage_known_retained = merge_retained(
                stage_known_retained,
                backup_error.retained,
            )
            stage_known_transient = tuple(
                dict.fromkeys(
                    (*stage_known_transient, *backup_error.transient)
                )
            )
        case unreachable:
            assert_never(unreachable)
    stage_attempt = attempt_private(
        bound,
        bound.stage,
        bound.stage_identity,
        lambda: retain_stage(
            bound,
            output,
            names,
            rename_noreplace,
            sync_parent,
            stage_known_retained,
            stage_known_transient,
        )
    )
    records = merge_retained(
        record_tuple(backup_attempt.record),
        record_tuple(stage_attempt.record),
    )
    errors = tuple(
        error
        for error in (backup_attempt.error, stage_attempt.error)
        if error is not None
    )
    if errors:
        retained = merge_retained(known_retained, records)
        transient = known_transient
        failures: tuple[Exception, ...] = ()
        for error in errors:
            retained = merge_retained(retained, error.retained)
            transient = tuple(
                dict.fromkeys((*transient, *error.transient))
            )
            failures = merge_failures(
                failures,
                (*error.failures, error),
            )
        context_error = PublicationCommitContextError(
            "one or more private artifacts could not be normalized; NEEDS_CONTEXT",
            retained,
            transient,
            failures,
        )
        raise finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            context_error,
        )
    return require_live_retained_evidence(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        records,
    )

```

Create `w3xtool/description_cache_publication_private_attempt.py` for the ordinary-exception
capture that lets the second private leaf run. It receives the exact leaf and optional held
identity. A typed publication error is already an authoritative evidence-bound outcome and
is returned unchanged; only an otherwise ordinary exception receives a fresh named-leaf
fallback and is stored in the wrapper's `failures` tuple. This prevents a completed
stage-location proof from being followed by a contradictory generic held-stage fallback and
returns one immutable attempt value:

```python
"""Independent error capture for one private publication leaf."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_named_leaf import capture_named_transient
from .description_cache_publication_models import RetainedCacheRecord
from .description_cache_publication_stage import BoundDescriptionCacheStage
from .description_cache_publication_stage_normalization import (
    capture_transient_record,
)


@dataclass(frozen=True, slots=True)
class PrivateAttempt:
    record: RetainedCacheRecord | None = None
    error: DescriptionCachePublicationError | None = None


def attempt_private(
    bound: BoundDescriptionCacheStage,
    path: Path,
    held_identity: DirectoryIdentity | None,
    operation: Callable[[], RetainedCacheRecord | None],
) -> PrivateAttempt:
    """Capture one failure so the other private name is still attempted."""
    try:
        return PrivateAttempt(record=operation())
    except Exception as cause:  # noqa: BROAD_EXCEPT_OK - independent private attempt
        match cause:
            case DescriptionCachePublicationError() as publication_error:
                return PrivateAttempt(error=publication_error)
            case Exception() as ordinary_error:
                error = PublicationCommitContextError(
                    f"private-artifact finalization raised an ordinary exception: "
                    f"{ordinary_error}; NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        match held_identity:
            case None:
                fallback = capture_named_transient(
                    bound.parent_descriptor,
                    bound.stage.parent,
                    bound.parent_identity,
                    path,
                )
            case (device, inode):
                fallback = capture_transient_record(
                    bound.parent_descriptor,
                    path,
                    bound.parent_identity,
                    (device, inode),
                )
            case unreachable:
                assert_never(unreachable)
        finalized = finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            error,
            later_evidence=fallback,
        )
        return PrivateAttempt(error=finalized)


def record_tuple(
    record: RetainedCacheRecord | None,
) -> tuple[RetainedCacheRecord, ...]:
    match record:
        case None:
            return ()
        case RetainedCacheRecord():
            return (record,)
        case unreachable:
            assert_never(unreachable)


__all__ = ("PrivateAttempt", "attempt_private", "record_tuple")
```

Create `w3xtool/description_cache_publication_backup_finalization.py` for backup-only
normalization. It never imports the stage locator or two-attempt orchestrator:

```python
"""Final normalization of one transaction-private backup leaf."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .description_cache_publication_errors import PublicationCommitContextError
from .description_cache_publication_evidence import finalize_error_evidence
from .description_cache_publication_named_leaf import read_named_leaf
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from .description_cache_publication_parent_identity import require_parent_identity
from .description_cache_publication_retention_durability import retain_durably
from .description_cache_publication_retention_names import RetainedCacheNames
from .description_cache_publication_stage import BoundDescriptionCacheStage


type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]


def retain_backup(
    bound: BoundDescriptionCacheStage,
    backup: Path,
    names: RetainedCacheNames,
    rename_noreplace: Rename,
    sync_parent: Sync,
) -> RetainedCacheRecord | None:
    """Retain one current backup object as recovery evidence."""
    require_parent_identity(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
    )
    proof = read_named_leaf(bound.parent_descriptor, backup.name)
    if proof.readable and proof.identity is None:
        return None
    if proof.identity is None:
        context_error = PublicationCommitContextError(
            "cannot prove final backup retention; NEEDS_CONTEXT",
            transient=(
                PublicationTransientRecord(
                    bound.stage.parent,
                    backup.name,
                    bound.parent_identity,
                    None,
                ),
            ),
            failures=proof.failures,
        )
        finalized = finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            context_error,
        )
        raise finalized
    identity = proof.identity
    return retain_durably(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        backup,
        identity,
        names,
        RetainedCacheRole.RECOVERY,
        rename_noreplace,
        sync_parent,
    )


__all__ = ("retain_backup",)
```

This split leaves `description_cache_publication_stage_finalization.py` with only
held-stage normalization and two-attempt orchestration, keeps the ordinary catch isolated
in `description_cache_publication_private_attempt.py`, and keeps backup normalization in its
own module. Measure all three independently; each targets below 200 pure LOC and none may
use `SIZE_OK`.

Extend `w3xtool/description_cache_publication_named_leaf.py` with the complete immutable
capture/reproof API below. Every function returns filesystem rows and exact read failures as
one `RetainedEvidenceReproof`; callers are forbidden to select `.transient` without also
merging `.failures` at the same typed boundary.

```python
"""Exact no-follow proofs for publication-parent leaves."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import merge_failures
from .description_cache_publication_fs import DirectoryIdentity, object_identity
from .description_cache_publication_models import (
    NamedLeafProof,
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedEvidenceReproof,
)


def read_named_leaf(parent_descriptor: int, name: str) -> NamedLeafProof:
    """Read one name without treating non-absence I/O failure as absence."""
    try:
        return NamedLeafProof(True, object_identity(parent_descriptor, name))
    except FileNotFoundError:
        return NamedLeafProof(True, None)
    except OSError as exc:
        return NamedLeafProof(False, None, exc)


def reprove_retained(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
) -> RetainedEvidenceReproof:
    """Rebuild exact and uncertain retained rows without losing read faults."""
    retained: list[RetainedCacheRecord] = []
    transient: list[PublicationTransientRecord] = []
    failures: tuple[Exception, ...] = ()
    for record in records:
        if record.path.parent != parent:
            transient.append(
                PublicationTransientRecord(
                    parent, record.path.name, parent_identity, None
                )
            )
            continue
        proof = read_named_leaf(parent_descriptor, record.path.name)
        failures = merge_failures(failures, proof.failures)
        if proof.readable and proof.identity is None:
            continue
        if proof.identity == record.identity:
            retained.append(record)
        else:
            transient.append(
                PublicationTransientRecord(
                    parent,
                    record.path.name,
                    parent_identity,
                    proof.identity,
                )
            )
    return RetainedEvidenceReproof(
        tuple(dict.fromkeys(retained)),
        tuple(dict.fromkeys(transient)),
        failures,
    )


def reprove_transient(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[PublicationTransientRecord, ...],
) -> RetainedEvidenceReproof:
    """Rebuild current transient rows and retain every non-absence read fault."""
    refreshed: list[PublicationTransientRecord] = []
    failures: tuple[Exception, ...] = ()
    for record in records:
        proof = read_named_leaf(parent_descriptor, record.leaf_name)
        failures = merge_failures(failures, proof.failures)
        if proof.readable and proof.identity is None and record.held_identity is None:
            continue
        refreshed.append(
            PublicationTransientRecord(
                parent,
                record.leaf_name,
                parent_identity,
                proof.identity,
                record.held_identity,
            )
        )
    return RetainedEvidenceReproof(
        transient=tuple(dict.fromkeys(refreshed)),
        failures=failures,
    )


def capture_named_transient(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    path: Path,
) -> RetainedEvidenceReproof:
    """Capture one current name, readable absence, or exact read failure."""
    proof = read_named_leaf(parent_descriptor, path.name)
    if proof.readable and proof.identity is None:
        return RetainedEvidenceReproof()
    return RetainedEvidenceReproof(
        transient=(
            PublicationTransientRecord(
                parent,
                path.name,
                parent_identity,
                proof.identity,
            ),
        ),
        failures=proof.failures,
    )


__all__ = (
    "capture_named_transient",
    "read_named_leaf",
    "reprove_retained",
    "reprove_transient",
)
```

Create `w3xtool/description_cache_publication_evidence.py` as the sole conversion point between descriptor-proved internal evidence and caller-visible paths. It deliberately accepts the held-parent fields rather than `BoundDescriptionCacheStage`, so stage-creation normalization can use it before a bound-stage value exists and the module does not introduce a cycle. `finalize_error_evidence()` preserves event order as earlier failures/records, the current error, later failures/records, then failures raised by its own reproofs. It always re-proves through the held descriptor before checking the public parent. If the public binding is gone, the returned error is the typed parent-context error, `retained` is empty, and every still-live held leaf is represented only as freshly rebuilt transient evidence:

```python
"""Caller-visible evidence boundaries for trusted-cache publication."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
    merge_retained,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_named_leaf import (
    reprove_retained,
    reprove_transient,
)
from .description_cache_publication_models import (
    PublicationTransientRecord,
    RetainedCacheRecord,
    RetainedEvidenceReproof,
)
from .description_cache_publication_parent_identity import require_parent_identity


def retained_as_transient(
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
) -> tuple[PublicationTransientRecord, ...]:
    """Demote held leaves whose public parent pathname is no longer bound."""
    return tuple(
        PublicationTransientRecord(
            parent,
            record.path.name,
            parent_identity,
            record.identity,
        )
        for record in records
    )


def finalize_error_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    error: DescriptionCachePublicationError,
    *,
    earlier_retained: tuple[RetainedCacheRecord, ...] = (),
    later_retained: tuple[RetainedCacheRecord, ...] = (),
    earlier_transient: tuple[PublicationTransientRecord, ...] = (),
    later_transient: tuple[PublicationTransientRecord, ...] = (),
    earlier_failures: tuple[Exception, ...] = (),
    later_failures: tuple[Exception, ...] = (),
    earlier_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
    later_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
    parent_loss_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
) -> DescriptionCachePublicationError:
    """Return one error containing only currently caller-addressable evidence."""
    merged = merge_retained(
        merge_retained(earlier_retained, earlier_evidence.retained),
        merge_retained(
            error.retained,
            merge_retained(later_evidence.retained, later_retained),
        ),
    )
    proof = reprove_retained(
        parent_descriptor,
        parent,
        parent_identity,
        merged,
    )
    transient_proof = reprove_transient(
        parent_descriptor,
        parent,
        parent_identity,
        (
            *earlier_transient,
            *earlier_evidence.transient,
            *error.transient,
            *later_evidence.transient,
            *later_transient,
            *proof.transient,
        ),
    )
    transient = transient_proof.transient
    failures = merge_failures(earlier_failures, earlier_evidence.failures)
    failures = merge_failures(failures, error.failures)
    failures = merge_failures(failures, later_evidence.failures)
    failures = merge_failures(failures, later_failures)
    failures = merge_failures(
        failures,
        (*proof.failures, *transient_proof.failures),
    )
    try:
        require_parent_identity(parent_descriptor, parent, parent_identity)
    except PublicationCommitContextError as parent_error:
        parent_error.replace_failures(
            merge_failures(
                (*failures, error),
                (*parent_loss_evidence.failures, *parent_error.failures),
            )
        )
        parent_error.replace_retained(())
        parent_error.replace_transient(
            tuple(
                dict.fromkeys(
                    (
                        *transient,
                        *parent_error.transient,
                        *retained_as_transient(
                            parent,
                            parent_identity,
                            proof.retained,
                        ),
                        *parent_loss_evidence.transient,
                    )
                )
            )
        )
        return parent_error
    if proof.retained != merged or proof.transient:
        return PublicationCommitContextError(
            "publication error contains unprovable retained evidence; NEEDS_CONTEXT",
            proof.retained,
            transient,
            merge_failures(failures, (error,)),
        )
    error.replace_retained(proof.retained)
    error.replace_transient(transient)
    error.replace_failures(failures)
    return error


def require_live_retained_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    records: tuple[RetainedCacheRecord, ...],
    *,
    parent_loss_evidence: RetainedEvidenceReproof = RetainedEvidenceReproof(),
) -> tuple[RetainedCacheRecord, ...]:
    """Require every record to remain exact and publicly addressable."""
    proof = reprove_retained(
        parent_descriptor,
        parent,
        parent_identity,
        records,
    )
    try:
        require_parent_identity(parent_descriptor, parent, parent_identity)
    except PublicationCommitContextError as parent_error:
        parent_error.replace_failures(
            merge_failures(
                (*proof.failures, *parent_loss_evidence.failures),
                parent_error.failures,
            )
        )
        parent_error.replace_retained(())
        parent_error.replace_transient(
            tuple(
                dict.fromkeys(
                    (
                        *proof.transient,
                        *retained_as_transient(
                            parent,
                            parent_identity,
                            proof.retained,
                        ),
                        *parent_loss_evidence.transient,
                    )
                )
            )
        )
        raise
    if proof.retained != records or proof.transient:
        raise PublicationCommitContextError(
            "retained evidence cannot be re-proved; NEEDS_CONTEXT",
            proof.retained,
            proof.transient,
            proof.failures,
        )
    return proof.retained


__all__ = (
    "finalize_error_evidence",
    "require_live_retained_evidence",
    "retained_as_transient",
)
```

Import `merge_failures` beside `merge_retained` in this evidence module. Any parent-binding
or retained-reproof replacement error keeps the incoming typed error and all of its original
failures in event order; evidence finalization may replace filesystem evidence but may never
erase the failure ledger.

Create `description_cache_publication_result_evidence.py` for the heavier success-only byte revalidation, keeping both evidence modules below 200 pure LOC. The initial retained/public-parent boundary is outside the validation `try`, so a parent-loss error is already final and cannot be caught a second time with an unbound `live` local. Every later parent-loss conversion captures the active leaf afresh through the held parent:

```python
"""Final byte and namespace proof before publication returns success."""

from __future__ import annotations

from pathlib import Path

from .description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
    merge_failures,
)
from .description_cache_publication_evidence import (
    finalize_error_evidence,
    require_live_retained_evidence,
)
from .description_cache_publication_fs import DirectoryIdentity
from .description_cache_publication_named_leaf import capture_named_transient
from .description_cache_publication_generation_evidence import (
    ExpectedPublishedGeneration,
    require_stable_generation_set,
)
from .description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
)


def require_live_result_evidence(
    parent_descriptor: int,
    parent: Path,
    parent_identity: DirectoryIdentity,
    output: Path,
    output_identity: DirectoryIdentity,
    proof: DescriptionCachePublicationProof,
    private_paths: tuple[Path, Path],
) -> DescriptionCachePublicationResult:
    """Revalidate the complete generation set and private namespace."""
    result = proof.result
    live = require_live_retained_evidence(
        parent_descriptor,
        parent,
        parent_identity,
        result.retained,
        parent_loss_evidence=capture_named_transient(
            parent_descriptor,
            parent,
            parent_identity,
            output,
        ),
    )
    expected_records = tuple(item.record for item in proof.retained_expectations)
    try:
        if expected_records != live:
            raise PublicationCommitContextError(
                "publication result has unmatched retained proof; NEEDS_CONTEXT"
            )
        require_stable_generation_set(
            parent_descriptor,
            parent,
            parent_identity,
            (
                ExpectedPublishedGeneration(
                    output,
                    output_identity,
                    result.active,
                ),
                *(
                    ExpectedPublishedGeneration(
                        expectation.record.path,
                        expectation.record.identity,
                        expectation.verified,
                    )
                    for expectation in proof.retained_expectations
                ),
            ),
            private_paths,
        )
    except DescriptionCachePublicationError as evidence_error:
        raise finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            evidence_error,
            earlier_retained=live,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                output,
            ),
        )
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - result evidence boundary
        context_error = PublicationCommitContextError(
            "publication result revalidation raised an ordinary exception; "
            "NEEDS_CONTEXT",
            failures=(exc,),
        )
        finalized = finalize_error_evidence(
            parent_descriptor,
            parent,
            parent_identity,
            context_error,
            earlier_retained=live,
            parent_loss_evidence=capture_named_transient(
                parent_descriptor,
                parent,
                parent_identity,
                output,
            ),
        )
        finalized.replace_failures(
            merge_failures(finalized.failures, (exc,))
        )
        raise finalized
    return result


__all__ = ("require_live_result_evidence",)
```

Import `merge_failures` in this result-evidence module. The ordinary boundary records the
exact exception and raises without replacing any parent-loss cause produced by finalization.

Stage normalization/finalization, the durable retainer, `ParentBoundValidator`, and the top-level publisher all use these shared boundaries. No other module may convert a held retained record into caller-visible evidence.

First add the single full-inventory ordering contract to
`description_cache_owned_schema.py`. This does not change the existing three-payload
manifest order or its digest; it controls only five-file writer and proof order:

```python
TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY: Final = tuple(
    sorted(
        (
            *TRUSTED_DESCRIPTION_CACHE_FILES,
            TRUSTED_DESCRIPTION_CACHE_MANIFEST,
            TRUSTED_DESCRIPTION_CACHE_MARKER,
        ),
        key=lambda name: name.encode("utf-8"),
    )
)
```

Export it from that module and replace every locally constructed five-file set/order in the
new writer and generation-I/O modules with this exact tuple. Inventory membership checks may
use `frozenset(TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY)`, but no second sorting key is
permitted.

Add this low-level proof model to `trusted_description_cache_models.py`; publication models import `VerifiedDescriptionCache` from this same low-level module, never from the public loader, so migration-model imports cannot cycle back through validation/source modules:

```python
@dataclass(frozen=True, slots=True)
class TrustedCacheLeafProof:
    """Exact identity and bytes written for one owned stage leaf."""

    name: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    sha256: str

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode


@dataclass(frozen=True, slots=True)
class TrustedCacheGenerationProof:
    """One stable directory identity and its complete five-leaf proof."""

    directory_device: int
    directory_inode: int
    leaves: tuple[TrustedCacheLeafProof, ...]

    @property
    def directory_identity(self) -> tuple[int, int]:
        return self.directory_device, self.directory_inode


@dataclass(frozen=True, slots=True)
class VerifiedDescriptionCacheGeneration:
    """Validated cache bytes bound to a complete stable generation proof."""

    verified: VerifiedDescriptionCache
    proof: TrustedCacheGenerationProof
```

Export all three proof models beside the existing payload/error/result models.

Create `w3xtool/description_cache_publication_stage_io.py` for the only stage-file writer. The allowed set is exactly the three payload names, manifest, and marker. `write_stage_text()` rejects every other or non-leaf name, uses `O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC`, writes and fsyncs through `write_chunks_to_descriptor()`, compares regular-file mode, `(device, inode)`, and final byte count through both `fstat()` and no-follow `stat(..., dir_fd=stage_descriptor)`, and returns the exact identity/size/SHA-256 proof. It never opens, creates, resolves, or writes `display_root`:

```python
_ALLOWED_STAGE_FILES: Final = frozenset(
    TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY
)
_FILE_CREATE_FLAGS: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_STAGE_IO_AVAILABLE: Final = bool(
    os.open in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.listdir in os.supports_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_EXCL")
    and hasattr(os, "O_NOFOLLOW")
)


def require_stage_io_support() -> None:
    """Fail before mutation unless the complete anchored stage API exists."""
    if not _STAGE_IO_AVAILABLE:
        raise DescriptionCachePublicationError(
            "descriptor-anchored trusted-cache stage I/O is unavailable"
        )


def write_stage_text(
    stage_descriptor: int,
    display_root: Path,
    name: str,
    text: str,
) -> TrustedCacheLeafProof:
    if name not in _ALLOWED_STAGE_FILES or Path(name).name != name:
        raise DescriptionCachePublicationError(
            f"unsafe trusted-cache stage leaf: {display_root / name}"
        )
    payload = text.encode("utf-8")
    try:
        descriptor = os.open(
            name,
            _FILE_CREATE_FLAGS,
            0o600,
            dir_fd=stage_descriptor,
        )
    except OSError as exc:
        raise DescriptionCachePublicationError(
            f"cannot create trusted-cache stage leaf: {display_root / name}",
            failures=(exc,),
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise DescriptionCachePublicationError(
                f"trusted-cache stage leaf is not regular: {display_root / name}"
            )
        size = write_chunks_to_descriptor(descriptor, (payload,))
        after = os.fstat(descriptor)
        named = os.stat(name, dir_fd=stage_descriptor, follow_symlinks=False)
        expected = opened.st_dev, opened.st_ino
        if (
            not stat.S_ISREG(after.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (after.st_dev, after.st_ino) != expected
            or (named.st_dev, named.st_ino) != expected
            or after.st_size != size
            or named.st_size != size
            or _stable_file_state(after) != _stable_file_state(named)
        ):
            raise DescriptionCachePublicationError(
                f"trusted-cache stage leaf changed while writing: {display_root / name}"
            )
        return TrustedCacheLeafProof(
            name,
            *expected,
            size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            hashlib.sha256(payload).hexdigest(),
        )
    finally:
        os.close(descriptor)


def _stable_file_state(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )
```

Create `description_cache_publication_build.py` with `build_description_cache_stage(source_root, stage_descriptor, display_root, accepted, rejections) -> tuple[TrustedCacheLeafProof, ...]`. Move the existing payload formatting, artifact hashing, manifest/marker construction into it, materialize all five text payloads first, then call `write_stage_text(stage_descriptor, display_root, name, texts[name])` for each name in `TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY`, finish with `sync_directory_descriptor(stage_descriptor)`, and return those five proofs in the same tuple order. It does not validate, publish, or use the display path for I/O.

Move complete-generation reads into the new focused `trusted_description_cache_generation_io.py`; keep `trusted_description_cache_io.py` responsible for opening/binding a cache leaf and delegating to it. The generation module exposes these exact internal contracts: `snapshot_trusted_cache_generation(descriptor: int, display_root: Path) -> TrustedCacheGenerationState`; `read_snapshot_payloads(descriptor: int, display_root: Path, snapshot: TrustedCacheGenerationState) -> TrustedDescriptionCachePayloads`; `prove_snapshot_payloads(before: TrustedCacheGenerationState, after: TrustedCacheGenerationState, payloads: TrustedDescriptionCachePayloads) -> TrustedCacheGenerationProof`; and `read_trusted_cache_from_descriptor(descriptor: int, display_root: Path, expected_leaves: tuple[TrustedCacheLeafProof, ...] | None = None) -> tuple[TrustedDescriptionCachePayloads, TrustedCacheGenerationProof]`.

`TrustedCacheNamedState` is an internal frozen/slots value containing `name: str` and
`details: os.stat_result`. `TrustedCacheGenerationState` is an internal frozen/slots value
containing the held directory's complete `os.stat_result` and exactly five
`TrustedCacheNamedState` values in `TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY` order.
`snapshot_trusted_cache_generation()` rejects extra/missing leaves, non-regular leaves,
duplicate names, and directory-identity change. `read_snapshot_payloads()` indexes those
states by name and passes each original `details` object unchanged to the existing
`read_owned_regular_file()`; it does not construct a reduced or synthetic stat value.

State stability is explicit rather than dataclass equality because reads may change access
time. `_stable_file_state(details)` returns `(st_dev, st_ino, st_size, st_mtime_ns,
st_ctime_ns, st_mode)`, and `_stable_generation_state(state)` returns the directory
device/inode/mode plus each `(name, *_stable_file_state(details))` tuple in owned-inventory
order. `prove_snapshot_payloads()` requires those stable keys to match, hashes all five
returned payloads in the same order, and produces `TrustedCacheLeafProof` values containing
all six stable metadata fields plus SHA-256. `read_trusted_cache_from_descriptor()` performs
snapshot → all-five read → snapshot and compares an optional writer proof only after the
complete round; it never closes the borrowed descriptor.

```python
@dataclass(frozen=True, slots=True)
class TrustedCacheNamedState:
    name: str
    details: os.stat_result


@dataclass(frozen=True, slots=True)
class TrustedCacheGenerationState:
    directory: os.stat_result
    leaves: tuple[TrustedCacheNamedState, ...]


type StableFileState = tuple[int, int, int, int, int, int]
type StableNamedState = tuple[str, int, int, int, int, int, int]
type StableGenerationState = tuple[
    int,
    int,
    int,
    tuple[StableNamedState, ...],
]


def _stable_file_state(details: os.stat_result) -> StableFileState:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
        details.st_mode,
    )


def _stable_generation_state(
    state: TrustedCacheGenerationState,
) -> StableGenerationState:
    return (
        state.directory.st_dev,
        state.directory.st_ino,
        state.directory.st_mode,
        tuple(
            (leaf.name, *_stable_file_state(leaf.details))
            for leaf in state.leaves
        ),
    )
```

The three exact aliases are internal to the generation-I/O module. Do not widen them to
`object`, `Any`, a raw dictionary, or a variadic heterogeneous escape hatch; the no-excuse
gate runs against this file in the same Task 2 commit.

Add `load_trusted_description_cache_from_descriptor(...)` to
`trusted_description_cache.py`. It returns `VerifiedDescriptionCacheGeneration`, not an
unbound cache value:

```python
def read_trusted_cache_from_descriptor(
    descriptor: int,
    display_root: Path,
    expected_leaves: tuple[TrustedCacheLeafProof, ...] | None = None,
) -> tuple[TrustedDescriptionCachePayloads, TrustedCacheGenerationProof]:
    """Read and prove one complete generation already held by the caller."""
    before = snapshot_trusted_cache_generation(descriptor, display_root)
    payloads = read_snapshot_payloads(descriptor, display_root, before)
    after = snapshot_trusted_cache_generation(descriptor, display_root)
    proof = prove_snapshot_payloads(before, after, payloads)
    if expected_leaves is not None and proof.leaves != expected_leaves:
        raise TrustedDescriptionCacheError(
            "held trusted cache differs from its writer proof"
        )
    return payloads, proof


def load_trusted_description_cache_from_descriptor(
    descriptor: int,
    display_root: Path,
    expected_leaves: tuple[TrustedCacheLeafProof, ...],
) -> VerifiedDescriptionCacheGeneration:
    """Validate bytes and retain their complete generation proof."""
    payloads, proof = read_trusted_cache_from_descriptor(
        descriptor,
        display_root,
        expected_leaves,
    )
    return VerifiedDescriptionCacheGeneration(
        validate_trusted_description_cache_payloads(payloads),
        proof,
    )
```

Public and held-parent loaders unwrap `.verified`; publication retains the proof. Add a third assertion
to `test_anchored_loader_proves_the_same_bytes_as_public_loader` requiring public,
held-parent, and held-stage `.verified` payloads to be byte-for-byte equal, and add a
deterministic hook that mutates the first leaf after it is read but before the fifth leaf;
the generation-wide post-snapshot must reject it even when the directory inode is unchanged.

Create `description_cache_publication_generation_evidence.py` with
`ExpectedPublishedGeneration(path, identity, verified)` and
`require_stable_generation_set(...)`. The latter opens every expected directory
descriptor-relative/no-follow and keeps all descriptors open. One proof round captures
every generation state and both private leaf states, reads every generation, recaptures the
entire set, validates every payload, and requires exact expected bytes. It then repeats that
*whole set* round once as the terminal reread and requires the two proof tuples to match.
Both private names must be absent in the before and after snapshots of both rounds. A private
leaf, directory-name replacement, parent loss, generation mutation, or proof mismatch raises
typed `NEEDS_CONTEXT`; its transient evidence is captured through the held parent. This is
the only final-result byte proof—no loop of independent loaders followed only by directory
inode checks is allowed. After the terminal hashes are known, it re-proves every generation
directory name and both private names, then calls `require_parent_identity()` as the final
filesystem operation. Neither this helper nor `require_live_result_evidence()` performs any
filesystem call after that parent proof; the latter immediately returns the already proven
immutable result value.

Change `publish_valid_stage()` to borrow `bound.parent_descriptor`, consume the already verified held-stage result, and never call `os.open(output.parent, ...)`. Immediately before its first rename it requires: public parent still equals `bound.parent_identity`, `descriptor_identity(bound.stage_descriptor) == bound.stage_identity`, and the no-follow `bound.stage.name` identity equals `bound.stage_identity`. `description_cache_publication_transaction.py` owns these checks and then dispatches the existing absent/replacement state machine.

In `publish_description_cache()`, first call the atomic-rename preflight and then the
stage-I/O preflight; only after both return may it create one identifier, names object,
stage, and backup. Remove all pathname existence/mkdir and `sync_directory(path)` calls.
Keep finalization inside the bound context so it can attach precise evidence:

```python
require_atomic_rename_support()
require_stage_io_support()

with create_stage_and_capture(
    stage,
    output,
    names,
    _rename_noreplace,
    _sync_parent,
) as bound:
    published_records: tuple[RetainedCacheRecord, ...] = ()
    try:
        leaf_proofs = build_description_cache_stage(
            source_root,
            bound.stage_descriptor,
            bound.stage,
            accepted,
            rejections,
        )
        generation = load_trusted_description_cache_from_descriptor(
            bound.stage_descriptor,
            bound.stage,
            leaf_proofs,
        )
        proof = _publish_valid_stage(
            bound,
            output,
            backup,
            names,
            generation,
        )
        published_records = proof.result.retained
        private_records = finalize_private_artifacts(
            bound,
            backup,
            output,
            names,
            _rename_noreplace,
            _sync_parent,
            published_records,
        )
        if private_records:
            raise PublicationCommitContextError(
                "successful publication required private evidence normalization; "
                "NEEDS_CONTEXT",
                merge_retained(published_records, private_records),
            )
        result = require_live_result_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            output,
            bound.stage_identity,
            proof,
            (bound.stage, backup),
        )
        bound.close_ledger.remember(result.retained, ())
        return result
    except Exception as exc:  # noqa: BROAD_EXCEPT_OK - transaction evidence boundary
        _raise_after_private_finalization(
            bound,
            backup,
            names,
            output,
            published_records,
            exc,
        )
```

The success path records the immutable result evidence before control leaves `with`; if
either descriptor close then fails, `__exit__()` raises typed `NEEDS_CONTEXT` with those
records. Every transaction failure is converted to a
`DescriptionCachePublicationError` before `__exit__()` runs, so close faults append context
to that same instance and preserve installed-target and other specific subtypes. The close
helper never calls a stat/reproof API because the descriptors may already be partly closed.

`_raise_after_private_finalization(...) -> Never` is the single ordinary-exception
boundary for this public transaction. It converts a non-publication `Exception` to
`DescriptionCachePublicationError(str(cause), failures=(cause,))`, attempts backup and stage normalization
independently through `finalize_private_artifacts()`, merges the cause's evidence with
`published_records` and every newly retained record through `finalize_error_evidence()`,
and raises the typed result without overwriting an existing explicit cause. `_raise_finalized()`
stores every distinct additional exception in `failures` and raises the typed instance
without a new `from` clause; the original explicit cause and implicit context therefore stay
unchanged. If finalization itself fails, its live evidence and ordered failure ledger are
merged with the original publication failure before propagation. It does not catch
`KeyboardInterrupt`, `SystemExit`, or `GeneratorExit` because those are not `Exception`.
These ordinary-exception catches, plus the raw/durable move, absent-output, recovery-sync,
created-stage, independent-private-attempt, result-evidence, and finalizer-evidence catches
shown above, are the only permitted `BROAD_EXCEPT_OK` sites in changed production paths.
Every site immediately converts or re-proves evidence and re-raises; none swallows a cause,
returns publication success, or catches a process-control exception.

Import `assert_never` and `merge_failures` into this top-level publication module; both
exception conversions below use exhaustive class-pattern matching and the typed failure
ledger rather than ad hoc runtime type checks or cause replacement.

```python
def _raise_after_private_finalization(
    bound: BoundDescriptionCacheStage,
    backup: Path,
    names: RetainedCacheNames,
    output: Path,
    published_records: tuple[RetainedCacheRecord, ...],
    cause: Exception,
) -> Never:
    match cause:
        case DescriptionCachePublicationError() as typed_error:
            publication_error = typed_error
        case Exception() as ordinary_error:
            publication_error = DescriptionCachePublicationError(
                str(ordinary_error),
                failures=(ordinary_error,),
            )
        case unreachable:
            assert_never(unreachable)
    known_records = merge_retained(
        published_records,
        publication_error.retained,
    )
    try:
        private_records = finalize_private_artifacts(
            bound,
            backup,
            output,
            names,
            _rename_noreplace,
            _sync_parent,
            known_records,
            publication_error.transient,
        )
    except Exception as finalization_cause:  # noqa: BROAD_EXCEPT_OK - finalizer evidence
        match finalization_cause:
            case DescriptionCachePublicationError() as typed_error:
                finalization_error = typed_error
            case Exception() as ordinary_error:
                finalization_error = PublicationCommitContextError(
                    f"private finalization raised an ordinary exception: "
                    f"{ordinary_error}; NEEDS_CONTEXT",
                    failures=(ordinary_error,),
                )
            case unreachable:
                assert_never(unreachable)
        finalization_error.replace_failures(
            merge_failures(
                (*publication_error.failures, publication_error),
                finalization_error.failures,
            )
        )
        finalized = finalize_error_evidence(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            finalization_error,
            earlier_retained=known_records,
            earlier_transient=publication_error.transient,
            parent_loss_evidence=capture_named_transient(
                bound.parent_descriptor,
                bound.stage.parent,
                bound.parent_identity,
                output,
            ),
        )
        _raise_finalized(finalized, finalization_cause)
    finalized = finalize_error_evidence(
        bound.parent_descriptor,
        bound.stage.parent,
        bound.parent_identity,
        publication_error,
        earlier_retained=published_records,
        later_retained=private_records,
        parent_loss_evidence=capture_named_transient(
            bound.parent_descriptor,
            bound.stage.parent,
            bound.parent_identity,
            output,
        ),
    )
    _raise_finalized(finalized, cause)


def _raise_finalized(
    error: DescriptionCachePublicationError,
    cause: Exception,
) -> Never:
    """Raise one typed boundary without replacing an existing cause."""
    if error is not cause:
        error.replace_failures(merge_failures(error.failures, (cause,)))
    raise error
```

The terminal generation-set proof observes both private names before and after each full
set read. If either name is reinserted during result revalidation, it raises into this same
boundary, which runs `finalize_private_artifacts()` a second time and forbids success even
when both late names can be normalized. Add deterministic late-stage, late-backup, and
simultaneous-insertion tests; each must show both names were attempted independently and
the final typed error contains only live retained/transient evidence.

`description_cache_publication.py` retains only transaction naming, adapter injection, the
bound lifecycle, and error/result propagation and must stay below 200 pure LOC. Stage,
stage-I/O, build, transaction, intended-role retention, recovery movement, held-stage
location, location scanning, finalization, backup finalization, private-attempt capture,
descriptor close, and commit each
remain one responsibility and target below 200 pure LOC. The complete durability and shared
intended-retention, durability, and error-evidence drafts are approximately 204, 229, and 245 pure LOC respectively, are explicitly in
the warning band, and may not grow during implementation; every module remains at or below
250 and no module may use a size suppression.

- [ ] **Step 7: Return retained records through publication, migration, and CLI**

Change the public publication signature:

```text
publish_description_cache(
    source_root: Path,
    output: Path,
    accepted: Sequence[ProvenDescriptionCandidate],
    rejections: Sequence[DescriptionCacheRejection],
) -> DescriptionCachePublicationResult
```

Extend the migration result with a trailing default and a construction boundary in `description_cache_migration_models.py` so the warning-band migration orchestrator shrinks instead of growing. Publication already imports migration models, so publication types are type-checking-only imports; `from __future__ import annotations` keeps those annotations lazy and prevents a runtime import cycle:

```python
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .description_cache_publication_models import (
        DescriptionCachePublicationResult,
        RetainedCacheRecord,
    )


@dataclass(frozen=True, slots=True)
class DescriptionCacheMigrationResult:
    accepted_count: int
    rejected_count: int
    rejections: tuple[DescriptionCacheRejection, ...]
    output: Path
    retained: tuple[RetainedCacheRecord, ...] = ()

    @classmethod
    def from_publication(
        cls,
        publication: DescriptionCachePublicationResult,
        rejections: Sequence[DescriptionCacheRejection],
        output: Path,
    ) -> DescriptionCacheMigrationResult:
        rows = tuple(rejections)
        return cls(
            len(publication.active.cache.entries),
            len(rows),
            rows,
            output,
            publication.retained,
        )
```

In `_migrate_from_source()` use the publication result without changing active cache bytes:

```python
publication = publish_description_cache(legacy_root, output, retained, rejections)
return DescriptionCacheMigrationResult.from_publication(
    publication,
    rejections,
    output,
)
```

After the existing CLI success summary, print records in result order:

```python
for retained in result.retained:
    print(
        single_line_text(
            f"保留对象：{retained.role.value} -> {retained.path}"
        )
    )
```

Catch `DescriptionCachePublicationError` before the existing generic `OSError` boundary and print its retained tuple to stderr before returning code `2`. The complete revised boundary is:

```python
def run_description_cache_cli(argv: tuple[str, ...]) -> int:
    """Parse, migrate, and map expected boundary failures to exit code 2."""
    try:
        options = parse_description_cache_cli_options(argv)
    except DescriptionCacheCliOptionError as exc:
        print(f"描述缓存参数错误：{exc}", file=sys.stderr)
        return 2
    try:
        result = migrate_description_cache(options)
    except DescriptionCachePublicationError as exc:
        detail = format_user_exception(
            exc,
            paths=(
                str(options.legacy_output),
                str(options.legacy_cache),
                str(options.output),
            ),
        )
        print(f"可信描述缓存迁移失败：{detail}", file=sys.stderr)
        for retained in exc.retained:
            print(
                single_line_text(
                    f"保留对象：{retained.role.value} -> {retained.path}"
                ),
                file=sys.stderr,
            )
        for transient in exc.transient:
            match transient.identity:
                case None:
                    object_identity_text = "unknown"
                case (device, inode):
                    object_identity_text = f"{device}:{inode}"
                case unreachable:
                    assert_never(unreachable)
            match transient.held_identity:
                case None:
                    held_identity_text = "unknown"
                case (device, inode):
                    held_identity_text = f"{device}:{inode}"
                case unreachable:
                    assert_never(unreachable)
            print(
                single_line_text(
                    "瞬态对象："
                    f"display-parent={transient.parent} "
                    f"parent={transient.parent_identity[0]}:"
                    f"{transient.parent_identity[1]} "
                    f"leaf={transient.leaf_name} object={object_identity_text} "
                    f"held={held_identity_text}"
                ),
                file=sys.stderr,
            )
        return 2
    except OSError as exc:
        detail = format_user_exception(
            exc,
            paths=(
                str(options.legacy_output),
                str(options.legacy_cache),
                str(options.output),
            ),
        )
        print(f"可信描述缓存迁移失败：{detail}", file=sys.stderr)
        return 2
    print(
        single_line_text(
            f"可信描述缓存迁移完成：接受 {result.accepted_count}，"
            f"拒绝 {result.rejected_count} -> {options.output}"
        )
    )
    for retained in result.retained:
        print(
            single_line_text(
                f"保留对象：{retained.role.value} -> {retained.path}"
            )
        )
    return 0
```

Add `assert_never` to this CLI module's imports.

Do not enumerate retained siblings in the loader, batch code, or GUI. A retained generation is loaded only when an operator explicitly passes that exact directory to `load_trusted_description_cache()`.

- [ ] **Step 8: Remove the old recursive primitive and reconcile inherited tests**

After all production callers use retention, remove `import shutil` and `remove_directory()` from `w3xtool/description_cache_publication_fs.py`; its `__all__` becomes exactly:

```python
__all__ = (
    "DirectoryIdentity",
    "directory_identity",
    "object_identity",
)
```

In `tests/description_cache_publication_fixture.py`, replace `private_publication_paths()` with two explicit helpers:

```python
def transient_publication_paths(output: Path) -> tuple[Path, ...]:
    patterns = (
        ".w3xray-description-cache-stage-*",
        ".w3xray-description-cache-backup-*",
    )
    return tuple(path for pattern in patterns for path in output.parent.glob(pattern))


def retained_publication_paths(output: Path) -> tuple[Path, ...]:
    return tuple(
        output.parent.glob(".w3xray-description-cache-retained-*-*")
    )


def assert_live_retained_records(
    records: tuple[RetainedCacheRecord, ...],
) -> None:
    for record in records:
        details = record.path.stat(follow_symlinks=False)
        assert (details.st_dev, details.st_ino) == record.identity
```

Update inherited success/failure tests to assert zero transient paths and the correct retained role. Delete the two obsolete removal-fault tests (`test_backup_removal_failure_restores_previous_owned_cache` and `test_partial_backup_removal_keeps_unprovable_output_for_recovery`) because production no longer has a removal seam; their required preservation and ambiguity behavior is covered by the real retention-race tests. Keep and adapt all exchange, parent-binding, validation, unsupported-host, foreign-destination, and final-sync cases. In the new race file, separately fault the parent sync immediately after successful `failed-output`, recovered `failed-stage`, and final-stage retention; fault the post-retain parent-binding check; and fault both active and retained revalidation after the commit sync error. Each surfaced typed error must still contain every record created earlier, and every recorded `(device, inode)` must match the no-follow on-disk object. In the durability file, wrap the real `directory_identity` with a `getattr()`-obtained test seam that replaces the publication parent after descriptor-relative `mkdir` but before the first stage identity read. Require typed `NEEDS_CONTEXT`, no deletion, one `PublicationTransientRecord` containing the original held-parent identity and exact stage inode, and CLI stderr visibility; the replacement parent must remain untouched. This is specifically a public-parent pathname replacement while the already-open parent descriptor remains authoritative; it is not a stage-leaf replacement inside the uncloseable `mkdirat`-to-stage-capture provenance window.

Rename the inherited final-sync success test to `test_final_parent_sync_failure_preserves_both_generations_and_needs_context`. It must now require `PublicationCommitContextError`, one error record with role `previous`, the new valid active cache, the old valid retained cache, and zero transient names. Adapt the output-takeover-after-final-sync test to require the same retained previous inode plus the untouched foreign output and displaced new generation. Adapt the existing output-takeover-after-exchange test to require the exact old inode under a `recovery` retained name when that role is free; the separate recovery-collision test is the only intentional transient case.

Run: `rg -n 'remove_directory|remove_stage|shutil\.rmtree|os\.rmdir|os\.unlink|\.unlink\(' w3xtool/description_cache_publication*.py` and `rg -n 'private_publication_paths' tests/test_description_cache_publication*.py tests/description_cache_publication_fixture.py`

Expected: no production removal matches and no stale fixture name. The test-side `monkeypatch.delattr(shutil, "rmtree")` guard is allowed because it proves publication never resolves the removed attribute.

Create `tests/test_description_cache_publication_imports.py` after every production module
exists. Each order runs in a fresh interpreter, so `sys.modules` caching cannot hide a
cycle:

```python
"""Clean-interpreter import-cycle proof for cache publication."""

from __future__ import annotations

import subprocess
import sys
from typing import Final

import pytest


_MODULES: Final[tuple[str, ...]] = (
    "w3xtool.atomic_rename",
    "w3xtool.description_cache_owned_schema",
    "w3xtool.trusted_description_cache_models",
    "w3xtool.trusted_description_cache_io",
    "w3xtool.trusted_description_cache_generation_io",
    "w3xtool.description_cache_publication_fs",
    "w3xtool.description_cache_publication_models",
    "w3xtool.description_cache_publication_errors",
    "w3xtool.description_cache_publication_retention_names",
    "w3xtool.description_cache_publication_retention_recovery",
    "w3xtool.description_cache_publication_retention_installed",
    "w3xtool.description_cache_publication_retention",
    "w3xtool.description_cache_publication_parent_identity",
    "w3xtool.description_cache_publication_named_leaf",
    "w3xtool.description_cache_publication_evidence",
    "w3xtool.description_cache_publication_retention_durability",
    "w3xtool.description_cache_publication_descriptor_close",
    "w3xtool.description_cache_publication_stage_normalization",
    "w3xtool.description_cache_publication_stage",
    "w3xtool.description_cache_publication_private_attempt",
    "w3xtool.description_cache_publication_backup_finalization",
    "w3xtool.description_cache_publication_stage_location_scan",
    "w3xtool.description_cache_publication_stage_location",
    "w3xtool.description_cache_publication_stage_finalization",
    "w3xtool.description_cache_publication_stage_io",
    "w3xtool.description_cache_publication_build",
    "w3xtool.description_cache_publication_rollback_selection",
    "w3xtool.description_cache_publication_recovery_state",
    "w3xtool.description_cache_publication_generation_evidence",
    "w3xtool.description_cache_publication_result_evidence",
    "w3xtool.description_cache_publication_parent",
    "w3xtool.description_cache_publication_recovery",
    "w3xtool.description_cache_publication_commit",
    "w3xtool.description_cache_publication_replacement",
    "w3xtool.description_cache_publication_absent",
    "w3xtool.description_cache_publication_transaction",
    "w3xtool.description_cache_publication",
    "w3xtool.description_cache_migration_models",
    "w3xtool.description_cache_migration",
    "w3xtool.description_cache_cli",
    "w3xtool.trusted_description_cache",
)


@pytest.mark.parametrize(
    "modules",
    (_MODULES, tuple(reversed(_MODULES))),
)
def test_publication_modules_import_in_clean_interpreter(
    modules: tuple[str, ...],
) -> None:
    code = "\n".join(f"import {module}" for module in modules)

    completed = subprocess.run(
        (sys.executable, "-c", code),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
```

- [ ] **Step 9: Run the complete Task 5 and loader parity lane**

Run:

```bash
uv run python -m pytest -q \
  tests/test_description_cache_publication_retention.py \
  tests/test_description_cache_retained_generations.py \
  tests/test_description_cache_publication_retention_collisions.py \
  tests/test_description_cache_publication_retention_durability.py \
  tests/test_description_cache_publication_retention_races.py \
  tests/test_description_cache_publication_recovery_durability.py \
  tests/test_description_cache_publication_stage_io.py \
  tests/test_description_cache_publication_descriptor_close.py \
  tests/test_description_cache_publication_imports.py \
  tests/test_description_cache_publication.py \
  tests/test_description_cache_publication_concurrency.py \
  tests/test_description_cache_publication_parent_binding.py \
  tests/test_description_cache_publication_validation.py \
  tests/test_description_cache_migration.py \
  tests/test_description_cache_migration_preflight.py \
  tests/test_description_cache_migration_state_security.py \
  tests/test_description_cache_manifest_binding.py \
  tests/test_description_cache_cli.py \
  tests/test_description_cache_cli_retention.py \
  tests/test_trusted_description_cache.py \
  tests/test_trusted_description_cache_anchored.py \
  tests/test_description_cache.py \
  tests/test_atomic_rename.py
```

Expected: PASS; public/anchored loader parity remains byte-for-byte equal, successful publication has no stage/backup names, and retained siblings are never selected implicitly.

- [ ] **Step 10: Run static, no-excuse, pure-LOC, and recursive-delete gates**

Define one exact changed-path set, then use the same set for Ruff, basedpyright, the no-excuse/oversized-module audit, and the final pure-LOC assertion:

```bash
PYTHON_PATHS=(
  w3xtool/description_cache_publication*.py
  w3xtool/atomic_rename.py
  w3xtool/description_cache_owned_schema.py
  w3xtool/description_cache_migration.py
  w3xtool/description_cache_migration_models.py
  w3xtool/description_cache_cli.py
  w3xtool/trusted_description_cache.py
  w3xtool/trusted_description_cache_generation_io.py
  w3xtool/trusted_description_cache_io.py
  w3xtool/trusted_description_cache_models.py
  tests/description_cache_publication_fixture.py
  tests/test_description_cache_publication*.py
  tests/test_description_cache_retained_generations.py
  tests/test_description_cache_cli_retention.py
  tests/test_atomic_rename.py
  tests/test_trusted_description_cache_anchored.py
)
uv run --with ruff ruff check --select F401,F821 "${PYTHON_PATHS[@]}"
uv run --with ruff ruff check "${PYTHON_PATHS[@]}"
uv run --with ruff ruff format --check "${PYTHON_PATHS[@]}"
uv run --with basedpyright basedpyright --level error "${PYTHON_PATHS[@]}"
uv run /Users/zhongerbing/.codex/skills/programming/scripts/python/check-no-excuse-rules.py \
  "${PYTHON_PATHS[@]}"
```

Expected: all five commands exit `0`; the dedicated first Ruff command makes F401/F821 an
explicit executable gate rather than an implication of syntax/import smoke tests. The
no-excuse audit's `oversized-module` rule reports every hand-written path at `<= 250` pure LOC. Do not add `SIZE_OK`, type-ignore, lint-ignore, or unrelated suppression. `BROAD_EXCEPT_OK` is permitted only on the exact ordinary-exception evidence catches in `retain_object()`, `move_object_to_recovery()`, `retain_durably()`, `_synchronize_installed_error()`, `publish_absent()`, `normalize_recovery_failure()`, `restore_previous_generation()`'s ordinary-cause wrapper, `create_stage_and_capture()` after the parent is held, `attempt_private()`, `close_publication_descriptors()`, `require_live_result_evidence()`, `publish_description_cache()`, and `_raise_after_private_finalization()`. Run `rg -n 'except (BaseException|Exception)|BROAD_EXCEPT_OK' w3xtool/description_cache_publication*.py`; require every `except Exception` line to carry one specific `BROAD_EXCEPT_OK` reason, no `BaseException` match, no site outside that function set, and no handler that swallows the cause or returns success.

Run: `! rg -n 'shutil\.rmtree|os\.rmdir|os\.unlink|\.unlink\(|remove_directory|remove_stage' w3xtool/description_cache_publication*.py`

Run this exhaustive production-path gate; the glob intentionally includes top-level
publication, evidence, result-evidence, generation-evidence, stage-I/O, and every future
focused sibling module:

```bash
RAW_RETAIN_PATHS=$(
  rg -l 'retain_object' w3xtool/description_cache_publication*.py | sort
)
EXPECTED_RAW_RETAIN_PATHS=$(printf '%s\n' \
  w3xtool/description_cache_publication_retention.py \
  w3xtool/description_cache_publication_retention_durability.py)
test "$RAW_RETAIN_PATHS" = "$EXPECTED_RAW_RETAIN_PATHS"
```

Expected: exit `0`; raw `retain_object()` appears in exactly the primitive and mandatory
durability adapter in production. Primitive tests may import it directly; no lifecycle,
evidence, loader, or top-level publication module may do so.

Run the matching recovery-boundary gate:

```bash
RECOVERY_MOVE_PATHS=$(
  rg -l 'move_object_to_recovery' w3xtool/description_cache_publication*.py | sort
)
EXPECTED_RECOVERY_MOVE_PATHS=$(printf '%s\n' \
  w3xtool/description_cache_publication_retention.py \
  w3xtool/description_cache_publication_retention_installed.py \
  w3xtool/description_cache_publication_retention_recovery.py)
test "$RECOVERY_MOVE_PATHS" = "$EXPECTED_RECOVERY_MOVE_PATHS"
```

Expected: exit `0`; lifecycle modules reach recovery movement only through the intended-role
state machine and its installed-target postcondition helper, both behind the durable wrapper.

- [ ] **Step 11: Commit the non-destructive lifecycle**

```bash
git add \
  w3xtool/atomic_rename.py \
  w3xtool/description_cache_owned_schema.py \
  w3xtool/description_cache_publication*.py \
  w3xtool/description_cache_migration.py \
  w3xtool/description_cache_migration_models.py \
  w3xtool/description_cache_cli.py \
  w3xtool/trusted_description_cache.py \
  w3xtool/trusted_description_cache_generation_io.py \
  w3xtool/trusted_description_cache_io.py \
  w3xtool/trusted_description_cache_models.py \
  tests/description_cache_publication_fixture.py \
  tests/test_atomic_rename.py \
  tests/test_description_cache_publication*.py \
  tests/test_description_cache_retained_generations.py \
  tests/test_description_cache_cli_retention.py \
  tests/test_trusted_description_cache_anchored.py
git commit -m "fix: retain non-active description caches"
```

---

### Task 3: Reconcile schema-5 integrity and acceptance planning with retained evidence

**Files:**
- Modify: `docs/superpowers/plans/2026-07-16-icon-text-evidence-gap-closure.md`
- Modify: `docs/superpowers/specs/2026-07-16-retained-description-cache-generations-design.md`
- Update local ignored ledger: `.superpowers/sdd/progress.md` (do not stage)

**Interfaces:**
- Extends future Task 10 with no-follow retained-object models, a canonical JSON report, and `inspect_retained_description_caches(active_root)`.
- Adds future CLI: `uv run main.py integrity retained-cache --active-root PATH --output FILE`.
- Changes future Task 11 wording from “no private leftovers” to “successful cache publication has zero stage/backup names; retained objects and impossible-normalization transient violations are reported separately”.
- Preserves: source-map and historical-output SHA-256/size/mtime checks and active-cache snapshot semantics.

- [ ] **Step 1: Amend Task 10 with exact retained-object contracts, CLI wiring, and tests**

Under Task 10's file list, add:

```markdown
- Create: `w3xtool/description_cache_retained_integrity_models.py`
- Create: `w3xtool/description_cache_retained_integrity.py`
- Create: `tests/test_description_cache_retained_integrity.py`
- Create: `tests/test_description_cache_retained_integrity_bounds.py`
- Create: `tests/test_description_cache_retained_integrity_stability.py`
- Create: `tests/test_integrity_cli_retained_cache.py`
```

Under Task 10's interfaces, add:

```markdown
- Produces: `CacheArtifactKind` (`directory`, `regular-file`, `symlink`, `special`, `unknown`), `RetainedArtifactValidation` (`valid-cache`, `partial-evidence`, `invalid-previous`, `unsafe-object`, `oversized`, `unstable`, `unreadable`), `RetentionArtifactReason` (`stage-transient`, `backup-transient`, `malformed-stage-name`, `malformed-backup-name`, `malformed-retained-name`, `unreadable-transient`), `RetainedDescriptionCacheArtifact`, `TransientDescriptionCacheArtifact`, `MalformedDescriptionCacheArtifact`, and `DescriptionCacheRetentionReport`. No formatter/parser accepts a reason outside that complete enum.
- Defines exact report fields: each retained artifact stores absolute path, transaction ID, closed role, no-follow kind, optional device/inode when unreadable, validation, optional size/file-count/entry-count/SHA-256, and optional safe relative problem path; each transient or malformed artifact stores absolute path, no-follow kind, optional device/inode, parsed transaction ID when available, and one closed `RetentionArtifactReason`. The report stores schema `1`, the exact active-root path and identity, and stable tuples. Canonical sort keys are `(absolute_path.as_posix().encode("utf-8"), role.value)` for retained and `(absolute_path.as_posix().encode("utf-8"), reason.value)` for transient/malformed; formatter and parser both reject any other ordering.
- Canonical JSON has exactly top-level keys `schema`, `active_root`, `active_device`, `active_inode`, `retained`, `transient`, and `malformed`. Retained rows have exactly `path`, `transaction_id`, `role`, `kind`, `device`, `inode`, `validation`, `size`, `file_count`, `entry_count`, `sha256`, and `problem_path`; transient/malformed rows have exactly `path`, `transaction_id`, `kind`, `device`, `inode`, and `reason`. Optional values serialize as JSON `null`, hashes are lowercase, and the document uses `ensure_ascii=False`, `sort_keys=True`, two-space indentation, and one final newline.
- Produces: `inspect_retained_description_caches(active_root)`, `format_description_cache_retention_report(report)`, and `parse_description_cache_retention_report(payload)`.
- Adds CLI: `integrity retained-cache --active-root PATH --output FILE`; `0` is allowed only when all retained rows are `valid-cache` or ordinary `partial-evidence` and transient/malformed are empty; `1` is required for `invalid-previous`, `unsafe-object`, `oversized`, `unstable`, `unreadable`, any transient, or any malformed row; `2` is required for request parsing, unsafe/unbindable active root, unstable publication-parent enumeration, report parsing, or report write failure.
- Uses this closed role × no-follow-kind classification; no implementation fallback may reinterpret a row:

  | Retained role | Stable directory | Stable regular file | Symlink / special | Unknown / unreadable |
  |---|---|---|---|---|
  | `previous` | `valid-cache` only after exact five-leaf validation; otherwise `invalid-previous` | `unsafe-object` | `unsafe-object` | `unreadable` |
  | `failed-stage`, `failed-output`, `recovery` | `partial-evidence` after a complete bounded tree proof | `partial-evidence` after a complete bounded file proof | `unsafe-object` | `unreadable` |

  `previous` therefore never reaches `partial-evidence`, and every non-directory
  `previous` exits `1`. Replacement of its top-level sibling identity remains a command
  boundary failure/exit `2` before this table is applied.
- Parses only exact `.w3xray-description-cache-retained-<32 lowercase hex>-<closed role>` sibling leaves; malformed retained-prefix leaves are violations and are never inferred into a role.
- Uses descriptor-relative no-follow traversal; directories receive a complete tree snapshot before any payload read and another complete tree snapshot after every payload read. A tree snapshot contains every relative path in UTF-8 path-byte order plus kind/device/inode/size/`mtime_ns`/`ctime_ns`/mode. The scanner requires the two tree snapshots to match before accepting that artifact's size/digest. Regular files receive the same bounded content proof, while symlinks/special files are recorded as unsafe without following or reading their target.
- Fixes scanner bounds as constants: `MAX_RETAINED_FILE_BYTES = 64 * 1024 * 1024`, `MAX_RETAINED_TREE_BYTES = 512 * 1024 * 1024`, `MAX_RETAINED_FILE_COUNT = 100_000`, `MAX_RETAINED_ENTRY_COUNT = 125_000`, and `MAX_RETAINED_DEPTH = 64`. Tree bytes sum regular-file payload sizes; file count counts regular files; entry count counts every no-follow directory entry. The retained root is depth `0`, its direct children are depth `1`, depth `64` is accepted, and the first entry at depth `65` is oversized. Crossing any bound stops that artifact scan without following another entry and yields `oversized`; it never truncates bytes and then reports a complete digest.
- Opens every hashed regular file with no-follow semantics and compares descriptor `(device, inode, size, mtime_ns, ctime_ns, mode)` before/after reading and against its anchored name. Permission/I/O denial for a named leaf produces explicit `unknown`/`identity=None` evidence and `unreadable`; only `FileNotFoundError` removes a formerly observed name. Inability to bind the explicitly requested active root is command-level code `2`.
- Holds the active cache parent descriptor for enumeration and validation and proves the requested active leaf identity before and after the whole scan; loss or replacement of that explicit root is a command-boundary code `2`, not a trustworthy report. A directory-role `previous` is eligible for payload validation only when its retained root snapshot contains exactly `TRUSTED_DESCRIPTION_CACHE_OWNED_INVENTORY` as five direct regular-file leaves, with no missing name, extra entry, or nested entry. Any stable inventory mismatch is `invalid-previous`/code `1`. Only then pass the exact five payload byte strings already read inside that artifact's stable before/read/after tree interval to `validate_trusted_description_cache_payloads()`; neither public nor held-parent pathname loader performs a second read. Stable invalid bytes are also `invalid-previous`, while any tree/identity change is `unstable`. `failed-stage`, `failed-output`, and `recovery` objects report evidence but are never loaded as description sources.
- One artifact-set round snapshots the relevant sibling namespace, proves every retained artifact with its complete tree interval, and snapshots the relevant siblings again. After all artifacts finish, the scanner repeats that entire artifact-set round and requires the ordered artifact states, tree states, payload digests, validation results, and sibling snapshots to equal the first round. An early retained child modified in place while a later artifact is scanned therefore fails even when the retained/publication parent inode and metadata do not change.
- Captures every publication-relevant sibling in UTF-8 name-byte order: the active leaf, every exact or malformed retained-prefix leaf, and every exact or malformed stage/backup-prefix leaf, including `(name, kind, device, inode, size, mtime_ns, ctime_ns, mode)`. Any insertion, removal, replacement, or metadata change in either set-wide round is a command-boundary code `2`; unrelated sibling churn is outside this report and does not invalidate it.
- Reports stage/backup leaves of every filesystem kind as transient integrity violations; batch transaction/quarantine checks remain in the existing batch integrity path.
- Maps reasons without fallback: a readable exact stage/backup name is `stage-transient`/`backup-transient`; a stage/backup/retained prefix that fails its exact grammar is `malformed-stage-name`/`malformed-backup-name`/`malformed-retained-name`; and an exact stage/backup leaf whose no-follow stat fails is `unreadable-transient`. An exact retained name whose leaf stat fails remains a retained row with validation `unreadable`, `kind=unknown`, and null device/inode; it has no reason field.
- Computes each complete tree SHA-256 from one UTF-8 stream of canonical JSON arrays `[relative_path, kind, device, inode, size, mtime_ns, ctime_ns, mode, file_sha256]`, one compact `separators=(",", ":")` array plus `"\n"` per entry in UTF-8 relative-path-byte order. Directory/symlink/special entries use JSON null for `file_sha256`; a bounded regular file uses its lowercase digest. An oversized, unstable, or unreadable tree has no complete tree digest.
```

Insert a retained-scanner RED substep immediately after Task 10 Step 3 has created the existing snapshot modules and before any retained-integrity production module is written. Keep core classification/format tests in `tests/test_description_cache_retained_integrity.py`, hard limits in `tests/test_description_cache_retained_integrity_bounds.py`, and mutation/readability/no-follow races in `tests/test_description_cache_retained_integrity_stability.py`; every file must remain below 200 pure LOC. These three files use only the then-importable `w3xtool.integrity_snapshot` module namespace, call the proposed scanner attribute inside each test body, and compare enum-like results by their string values. Require collection success plus runtime failure; a missing-module or top-level missing-import error is a test defect. Run this scanner-only RED exactly once:

```bash
uv run python -m pytest -q \
  tests/test_description_cache_retained_integrity.py \
  tests/test_description_cache_retained_integrity_bounds.py \
  tests/test_description_cache_retained_integrity_stability.py
```

Expected: tests collect and fail at the in-body scanner lookup/observable assertion because the existing snapshot namespace has no retained-cache behavior; no failure is a collection import error. Only after this RED may the dedicated retained model/scanner modules be created and the three test imports refactored without changing assertions.

Complete the parent Task 10 Steps 4–5 next so `w3xtool.integrity_cli` and
`run_integrity_cli()` really exist with the base `snapshot`/`verify` actions. Immediately
after Step 5, create `tests/test_integrity_cli_retained_cache.py`, import that existing
function normally, and add all retained-cache exit-code cases. Before adding the
`retained-cache` parser/action branch, run this separate CLI RED:

```bash
uv run python -m pytest -q tests/test_integrity_cli_retained_cache.py
```

Expected: collection succeeds and the existing CLI rejects the unknown `retained-cache`
action at the observable exit-code/output assertion. Only then extend the existing CLI and
run all four retained-integrity files together for GREEN. This ordering never asks a test to
import `w3xtool.integrity_cli` before the parent plan creates it.

Use the trusted-cache fixture to create independently valid `active` and `previous` roots, then rename the latter to an exact retained `previous` sibling. The final GREEN test shape is:

```python
def test_retained_integrity_separates_valid_partial_and_transient_objects(
    tmp_path: Path,
) -> None:
    active = published_cache(tmp_path / "active-source", raw="active")
    old = published_cache(tmp_path / "old-source", raw="previous")
    previous = active.parent / (
        ".w3xray-description-cache-retained-"
        f"{'1' * 32}-previous"
    )
    old.rename(previous)
    failed = active.parent / (
        ".w3xray-description-cache-retained-"
        f"{'2' * 32}-failed-stage"
    )
    failed.mkdir()
    (failed / "partial.bin").write_bytes(b"partial")
    transient = active.parent / (
        ".w3xray-description-cache-stage-"
        f"{'3' * 32}"
    )
    transient.write_bytes(b"transient")
    unsafe = active.parent / (
        ".w3xray-description-cache-retained-"
        f"{'4' * 32}-recovery"
    )
    unsafe.symlink_to(tmp_path / "outside", target_is_directory=True)

    report = inspect_retained_description_caches(active)

    by_role = {item.role: item for item in report.retained}
    assert by_role[RetainedCacheRole.PREVIOUS].validation is (
        RetainedArtifactValidation.VALID_CACHE
    )
    assert by_role[RetainedCacheRole.PREVIOUS].kind is CacheArtifactKind.DIRECTORY
    assert by_role[RetainedCacheRole.FAILED_STAGE].size == len(b"partial")
    assert len(by_role[RetainedCacheRole.FAILED_STAGE].sha256) == 64
    assert by_role[RetainedCacheRole.RECOVERY].kind is CacheArtifactKind.SYMLINK
    assert by_role[RetainedCacheRole.RECOVERY].validation is (
        RetainedArtifactValidation.UNSAFE_OBJECT
    )
    assert len(report.transient) == 1
    assert report.transient[0].path == transient
    assert report.transient[0].kind is CacheArtifactKind.REGULAR_FILE
    assert load_trusted_description_cache(active).cache.lookup(
        "物品", "ratf", "扩展提示", None
    )[0].raw_value == "active"
    assert parse_description_cache_retention_report(
        format_description_cache_retention_report(report)
    ) == report
```

Before implementing the scanner, add focused RED cases for: an exact-limit regular file and one-byte-oversized file; exact and exceeded total-tree byte limits; exact and exceeded file-count and entry-count limits; a retained root at depth `0`, an accepted child at depth `64`, and a rejected child at depth `65`; a file replaced or mutated between pre/post `fstat`; an unreadable entry retained with `kind=unknown` and `identity=None`; symlinks at both top level and inside a retained directory; an active-root symlink and a mid-scan active-root replacement rejected with code `2`; special objects; every exact closed reason code and rejection of an unknown reason; malformed retained/stage/backup leaves; canonical field-set/order/format/parse round-trip; and parser rejection of unknown states, unsafe problem paths, unsorted rows, or inconsistent totals/digests. For retained `previous`, separately remove one owned regular leaf, add one extra ordinary file, add one nested directory entry, and create exact-role top-level regular-file, symlink, and special-object siblings. The three stable inventory mismatches must be `invalid-previous`; every non-directory case must be `unsafe-object`; all six produce report/CLI code `1` and none may be `valid-cache` or `partial-evidence`. Add deterministic hooks between the initial relevant-sibling snapshot and final snapshot: insert a stage leaf, insert a malformed retained-prefix leaf, remove an existing backup leaf, and replace an existing retained leaf. Each must exit `2` and must never emit a clean report. Separately, mutate an already-read early child in place with the same inode and size while a later retained artifact is being scanned; the terminal whole-set round must return `unstable`/code `1`. For `previous`, inject distinct valid bytes if any second loader read occurs, require validation of the first round's captured bytes, and prove both the public and held-parent pathname loaders are never called. Replacing the top-level `previous` sibling with a different valid cache inode during either round is relevant-sibling instability: require command-boundary code `2` and no report, never `unstable`/code `1` or `valid-cache`. Only mutation below a still-exact held top-level sibling produces the per-artifact `unstable`/code `1` result. Use injected read/stat seams or real descriptor operations, never sleeps. Add CLI tests in the dedicated new CLI file for all three exit codes and assert the JSON output exists for codes `0` and `1`; code `0` covers only `valid-cache` plus ordinary `partial-evidence`, code `1` covers every per-artifact violation plus transient/malformed, and code `2` is reserved for command/report boundary failure, including unstable relevant-sibling enumeration.

Extend Task 10 Step 5's `integrity` parser/action wiring, Step 6's pytest/Ruff/basedpyright paths, Step 7/9's `STRICT_PATHS` expectations, Step 10's README/operator commands, and Step 12's `git add` list with both new modules and all four new tests. The report file is written with `write_text_safely()` and may be an unrelated regular file in the active cache's parent, but it must never be inside the active directory or any retained/transient artifact.

- [ ] **Step 2: Amend Task 11 commands and expected results**

After the initial cache migration and after every deliberate replacement, run:

```bash
uv run main.py integrity retained-cache \
  --active-root /Users/zhongerbing/Documents/xm/war3_xg/trusted-description-cache-v5 \
  --output /Users/zhongerbing/Documents/xm/war3_xg/schema5-retained-cache-integrity.json
```

For the required first migration into an absent `trusted-description-cache-v5`, expected exit is `0`, retained count is zero, and transient count is zero. If an operator deliberately reruns migration against an existing owned v5 cache, expected exit remains `0`, exactly one `previous` artifact validates as a complete cache, the active cache remains valid, and transient count remains zero. A code `1` report aborts acceptance but preserves every reported artifact for operator review.

Remove shell checks that filter with `find -type d`; the no-follow integrity action must see regular files, symlinks, and special objects as well as directories. Keep batch `transaction`/`quarantine` checks unchanged because they belong to batch publication.

- [ ] **Step 3: Clarify the impossible-normalization boundary and update the local SDD ledger**

After Tasks 1–2 pass review, change the supporting specification status without claiming the future Task 10/11 work has run:

```markdown
**Status:** publication lifecycle implemented; retained-integrity implementation and real acceptance pending Tasks 10–11
```

Clarify the integrity paragraph: zero transient names is mandatory for success and for failures where an exact object can reach a free retained role. If every legal retained role is occupied or the filesystem rejects the required atomic no-replace move, overwriting and deletion remain forbidden; the command returns `NEEDS_CONTEXT`, leaves the exact transient evidence reachable, and the integrity action reports a violation. This resolves the logical conflict between fixed no-replace names and an adversary occupying every target without weakening preservation.

Append this local status line to ignored `.superpowers/sdd/progress.md` beneath Task 5:

```markdown
  - retained-generation publication lifecycle: complete (review clean; integrity acceptance remains in Tasks 10–11)
```

- [ ] **Step 4: Verify the planning reconciliation and commit it**

Run: `rg -n 'retained|transient|stage|backup|transaction|quarantine' docs/superpowers/plans/2026-07-16-icon-text-evidence-gap-closure.md docs/superpowers/specs/2026-07-16-retained-description-cache-generations-design.md .superpowers/sdd/progress.md`

Expected: the main plan explicitly defines the retained-cache CLI, all object kinds, exit codes, static/commit paths, and separate retained/transient acceptance; no sentence requires automatic deletion or extraction-time loading of retained siblings.

Run: `git diff --check`

```bash
git add docs/superpowers/plans/2026-07-16-icon-text-evidence-gap-closure.md docs/superpowers/specs/2026-07-16-retained-description-cache-generations-design.md
git commit -m "docs: reconcile retained cache integrity"
```

Confirm `git status --short --ignored .superpowers/sdd/progress.md` reports the ledger as ignored and that it is not present in the commit.

---

## Final verification for this amendment

- [ ] Run the focused Task 5 lane from Task 2 Step 9 with no skipped case.
- [ ] Run: `uv run w3xray-quality`.
- [ ] Run: `uv run w3xray-test`.
- [ ] Run Ruff format/check, basedpyright, no-excuse, and pure-LOC gates for every changed Python path.
- [ ] Run: `! rg -n '\bisinstance\(' w3xtool/description_cache_publication*.py w3xtool/description_cache_migration.py w3xtool/description_cache_migration_models.py w3xtool/description_cache_cli.py tests/test_description_cache_publication*.py tests/test_description_cache_retained_generations.py tests/test_description_cache_cli_retention.py`.
- [ ] Run: `! rg -n 'shutil\.rmtree|os\.rmdir|os\.unlink|\.unlink\(|remove_directory|remove_stage' w3xtool/description_cache_publication*.py`.
- [ ] Run: `git diff --check` and `git status --short`.
- [ ] Require zero transient stage/backup names in every successful fixture while allowing and validating intentional retained siblings.
- [ ] Confirm no source map, historical output, v5 external output, executable, DLL, or game process was read or mutated by these unit/integration tests.

## Plan self-review result

- Spec coverage: Task 1 covers the closed role model, generic retained/transient records, exact names, atomic no-replace preservation, inode proof, collision fallback, recovery source reacquisition, and directory/file/symlink source-swap races. Task 2 covers descriptor-bound stage creation, first publication, replacement, recovery, two-round stage-location proof across all four retained roles, known published evidence, non-self exception causes, complete clean-interpreter import coverage, ordered result/CLI visibility, loader non-discovery, transient semantics, and all Task 5 gates. Task 3 covers descriptor-anchored retained integrity metadata, the closed role × kind table, and reconciles future 39-map acceptance language.
- Destructive-authority removal: Task 1 makes the preservation primitive's focused tests green while the prewritten lifecycle suite remains intentionally RED; Task 2 migrates every caller and removes `shutil` plus `remove_directory()` in the single commit where the complete RED suite turns GREEN.
- Result consistency: successful retained records flow unchanged from `DescriptionCachePublicationResult` into `DescriptionCacheMigrationResult` and CLI stdout; failure records merge in transaction order with stable de-duplication, every transient path/inode is rebuilt from the current held namespace, and both retained and stage-creation transient evidence reach CLI stderr.
- Type consistency: all lifecycle functions use `RetainedCacheRole`, `RetainedCacheRecord`, and `PublicationTransientRecord`; retained paths are generated only by `RetainedCacheNames` from one transaction identifier.
- Failure truth: identity mismatch, parent loss, destination collision, source-name reacquisition, uncertain reverse state, stage-location set change, whole-generation mutation, or late private-name insertion always preserves reachable objects and raises typed `NEEDS_CONTEXT`; once intended `previous` is installed, `RetainedObjectInstalledContextError` forbids rollback. No failure guesses which directory may be deleted, treats directory inode stability as byte stability, or assigns an exception as its own cause.
- Compatibility: the five active owned files, marker/manifest schema, public loader, source replay, batch dependency fingerprint, exit code `0` for successful retention, and exit code `2` for typed publication failure remain unchanged.
- Module size: new model, name validation, intended-role retention, installed-target postconditions, recovery movement/reproof, retention durability, parent identity, rollback selection, recovery state, stage resource, descriptor close, stage normalization, stage-location orchestration, stage-location scanning, held-stage finalization, backup finalization, private-attempt capture, stage I/O, stage-build, generation I/O, generation-set evidence, error evidence, result evidence, integrity-model, integrity-scan, and behavior-specific test files each own one responsibility so the warning-band replacement, migration, CLI test, and existing publication test files do not grow. The prior 352-pure-LOC retention draft is now approximately 204/92/174 across intended-role, installed-target, and recovery modules; the prior 260-pure-LOC finalizer draft is split into held-stage/orchestrator, private-attempt, and backup modules, each below 200; stage-location orchestration and immutable scanning are separate sub-200 modules. Intended retention (~204), durability (~229), and shared error evidence (~245) are the only planned warning-band modules and may not grow. Recalculate after implementation; every created or edited hand-written module remains at or below `250` with no size suppression.
- Placeholder scan: the plan contains no unresolved or future-value placeholders; every code path, command, output contract, and durable ledger line is explicit.
