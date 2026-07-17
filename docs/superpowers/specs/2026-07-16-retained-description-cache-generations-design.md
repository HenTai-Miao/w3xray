# Retained Trusted-Description Cache Generations Design

**Date:** 2026-07-16  
**Status:** approved approach; implementation pending  
**Amends:** `2026-07-16-icon-text-evidence-gap-closure-design.md`

## Context

Trusted-description cache publication already validates owned generations through held
directory descriptors and atomically swaps an existing output with a validated stage.
The remaining unsafe operation is recursive directory deletion. On supported macOS and
Linux targets, recursive deletion still ends with a pathname lookup; neither platform
offers a portable, unprivileged operation that recursively removes a non-empty directory
by its already-open descriptor. An inode check followed by `rmtree(name)` therefore has
an unavoidable check/use interval in which the name can be replaced.

Publication must prefer preservation over cleanup. A cache migration must never guess
which concurrently visible directory is safe to delete.

## Decision

The cache publisher will not recursively delete stage, previous-generation, rollback, or
recovery objects. Whenever an exact object can reach an unoccupied legal destination, it
will atomically move that object into an intentional retained-evidence name and leave its
bytes unchanged.

Preservation is the higher-order invariant. If every legal retained name is occupied, the
publication parent loses its captured binding, or the filesystem rejects the required
atomic no-replace operation, the publisher must not overwrite, delete, or guess. It keeps
every reachable object at its current name and returns typed `NEEDS_CONTEXT`. Therefore
zero transient names is mandatory for success and for every failure that can be normalized
safely, but is not claimed for an impossible-to-normalize adversarial failure.

The active output remains the exact five-file owned cache defined by the parent design.
Retained evidence is a sibling of the active output, not a child of it, and is never
implicitly loaded or promoted.

## Naming and identity

Each migration allocates one cryptographically random transaction identifier. Transient
names remain:

- `.w3xray-description-cache-stage-<transaction-id>`;
- `.w3xray-description-cache-backup-<transaction-id>`.

Before returning success, and before returning any failure whose exact object can reach a
free retained role, every surviving transient name is atomically renamed with no-replace
semantics to:

```text
.w3xray-description-cache-retained-<transaction-id>-<role>
```

The closed role set is:

- `previous`: the previously active, fully verified generation after successful
  replacement;
- `failed-stage`: a stage that could not be published or completely proved;
- `failed-output`: a newly installed output that failed post-publication proof;
- `recovery`: an object whose exact role cannot be proved after an interrupted or
  concurrent namespace change.

Names are single safe leaves. The publisher records and compares `(device, inode)` before
and after each move. It never overwrites an existing retained name. A retained record may
describe a directory, regular file, symlink, or special object encountered during a race;
only a proven directory may be treated as a cache candidate by an explicit operator action.
Every return or ordinary exception from an atomic-move callable, including
`FileExistsError`, enters the same two-name postcondition proof. Exception type is never
used as evidence that no move occurred. A true occupied target, a reacquired source, an
unreadable side, and a target installed before the callable raised are distinct proved
states, and every reachable source and destination side remains present in retained or
transient evidence.

A readable `FileNotFoundError` result is absence, not an unknown transient. This applies to
an intended target that remained absent, to an already-`recovery` candidate that disappeared,
and to every other held-less named proof. An absent name carries `held_identity` only when a
separate still-open descriptor proves an object that has not been uniquely located at any
legal current name; absence by itself never manufactures an `identity=None` record.
Every other `OSError` from a no-follow named-leaf read is uncertainty, not absence. The
current filesystem evidence therefore keeps that leaf with `identity=None`, while the exact
caught exception object is appended to the typed failure ledger at the same boundary. Named
proof values and immutable scan states carry that exception until conversion; no helper may
reduce it to a boolean, `None`, or display text.

A recovery move is clean only when the source side is readably absent and the recovery
side names the exact expected inode. If a normal-return move is followed by another object
reacquiring the source name, the recovery record and the reacquired-source transient are
both surfaced under typed `NEEDS_CONTEXT`; the foreign source can never be discarded merely
because the expected inode reached `recovery`.

## Publication flow

Before allocating a transaction UUID, opening the publication parent, calling `mkdir`,
invoking the stage writer, or calling any rename adapter, the publisher independently proves
that the host supplies both required atomic rename operations and every
descriptor-relative/no-follow stage-I/O capability. Either failed preflight is terminal:
unsupported hosts fail with zero UUID, descriptor-relative `mkdir`, stage-writer,
no-replace-adapter, and exchange-adapter calls and with no filesystem mutation.

### Stage-creation platform precondition

POSIX `mkdirat` returns only success or failure; it does not return a descriptor or the
identity of the directory it created. A same-permission, non-cooperating process that can
mutate the publication parent can therefore replace the stage name after `mkdirat` returns
but before the publisher's first no-follow `openat` plus descriptor-identity capture. If the
replacement survives both operations, repeated named `stat`/descriptor comparisons prove
only the replacement's current identity; they cannot prove that it is the directory created
by this transaction.

The publication safety contract consequently requires that no such replacement occur in
that interval, enforced by publication-parent permissions or external cooperation. The
zero-write and foreign-tree byte-for-byte guarantees begin only after the no-follow stage
descriptor has been opened and its identity successfully captured. Closing this provenance
window against an equally privileged hostile namespace writer would require a platform
primitive that creates and returns a bound directory descriptor; it is not claimed here.

Before either supported flow, the publisher opens and binds the output parent, creates the stage with
descriptor-relative `mkdir`, then separately opens the current stage leaf with no-follow
semantics and captures its descriptor identity under that precondition. It keeps both
descriptors open through stage construction and the publication transaction.
Every cache file is created exclusively through the held stage descriptor; no build write
resolves the parent or stage pathname again. The publisher validates the built bytes through
that same stage descriptor. Validation is generation-wide rather than five unrelated file
reads: it snapshots every owned leaf, reads and hashes all five files, snapshots the whole
inventory again, and requires device, inode, size, modification time, change time, mode, and
SHA-256 stability for
the complete interval. Immediately before the first atomic rename it repeats that complete
held-stage proof and separately proves that the stage leaf still names the held inode. From
successful held-stage capture onward, a parent or stage-leaf takeover therefore cannot
receive a single cache byte, and an in-place or self-consistent five-file substitution cannot
be published from stale validation.

Creation failures are normalized while the parent descriptor is still held. The creation
boundary catches every ordinary `Exception` after the parent is opened, including non-I/O
exceptions raised after `mkdir`; it does not catch `KeyboardInterrupt`, `SystemExit`, or
`GeneratorExit`. If a directory
identity was proved but initial parent synchronization fails, the exact stage moves to
`failed-stage`. If only a generic no-follow identity can be proved, the object moves to
`recovery`. Each move is followed by parent synchronization and identity proof and its
record is attached to typed `NEEDS_CONTEXT`. Only an unavailable identity, lost parent
binding, occupied legal target, or rejected atomic no-replace operation may leave a
transient; that error records the held parent identity, leaf name, and best available
no-follow named-leaf identity. When the stage descriptor was successfully captured before
the later takeover, the transient record also stores that distinct held identity; named and held
objects are never conflated.
Only the descriptor-relative `mkdir` call may classify `FileExistsError` as a stage-name
collision. Once `mkdir` returns, a `FileExistsError` from open, identity proof, validation,
or synchronization is an ordinary post-creation failure and must run the same
`failed-stage`/`recovery` normalization as every other exception.

### First publication

1. Build the stage and validate it through the descriptor-anchored loader.
2. Atomically rename the stage to an absent output with no-replace semantics.
3. Synchronize the parent and validate the active output through the held descriptor.
4. If output proof fails, atomically retain the exact installed directory as
   `failed-output`; leave the requested output absent and return a typed error.

If `failed-output` retention itself cannot be completed or proved, the surfaced error keeps
the `PublicationCommitContextError` or installed-target subtype, includes both the original
publication cause and the retention cause, and carries their merged live evidence. A
secondary retention failure never collapses `NEEDS_CONTEXT` into a generic publication
error.
When `failed-output` retention succeeds, the original post-install typed error instance is
updated with the live record and re-raised; successful preservation never reconstructs it as
the base publication error or changes its existing cause.

### Replacement

1. Validate both the stage and the existing owned output through the held parent
   descriptor.
2. Atomically exchange stage and output; the active output name is never absent.
3. Prove the new output and the displaced previous generation by their captured
   identities.
4. Atomically rename the displaced previous generation to the `previous` retained name.
5. Synchronize the parent. Successful retention is the commit point; return success with
   the new active output and retained path.

Once the exact previous generation has reached its intended retained name, rollback is no
longer permitted. A later parent synchronization, binding, or evidence failure preserves
`output=new` and `previous=old` and returns typed `NEEDS_CONTEXT`; it never consumes the
already installed retained generation. Collision/recovery errors that never installed the
intended `previous` role remain eligible for exact identity-driven rollback.

If the `previous` name is occupied, the generic retainer may first move the exact displaced
old generation to `recovery`. Rollback selects the unique live retained record whose
identity equals the captured old generation, exchanges from that recorded path, restores
the old active generation, and retains the new generation as `failed-stage`. The consumed
`recovery` record is replaced by the live `failed-stage` record; no surfaced record may
name a path/inode pair that can no longer be proved.

### Failure and ambiguity

Whether a move callable returns or raises is not treated as proof of its completion state.
The publisher independently re-reads both source and destination. An exact expected inode
at `recovery` with that inode absent from the source is recorded as a completed recovery
even when the callable raised after performing the atomic move. An exact source, an
occupied or foreign destination, or an unreadable side is reported separately; no reachable
side is omitted or guessed.

If a move's postconditions cannot be proved, the publisher performs a reverse move only
when every involved name and inode is still exact and the intended `previous` retained role
was not already installed. Otherwise it preserves all reachable objects and raises
`PublicationCommitContextError` containing `NEEDS_CONTEXT`. Before an error crosses the
public boundary, retained and transient evidence is rebuilt from the current held-parent
namespace; a path consumed by exchange or retention is never reported with its stale inode.
Only `FileNotFoundError` proves that a named leaf disappeared. A replacement is reported as
a transient with its current identity, while permission or I/O uncertainty is reported with
an unknown identity. After the last retained/transient leaf reproof, the public-parent
binding check is the final filesystem operation at every caller-visible result or error
boundary. If that last check fails, the most recently proved retained records are demoted to
transient evidence without another filesystem read.

Every typed publication error also carries an ordered, identity-de-duplicated tuple of the
exact independent failure objects caught during the transaction. Event order is the order in
which operations fail, not the order in which errors are aggregated; distinct objects with
equal type or text remain distinct. Atomic-move, named-read, parent-proof, stage-creation,
retention, synchronization, recovery, normalization, evidence-finalization, and descriptor-
close failures all enter this tuple. One explicit `__cause__` may additionally describe the
immediate operation, but ledger membership never depends on whether that object is also the
cause. A later boundary first appends its failure, finalizes evidence, and then bare-raises the
returned typed object; it may never replace a pre-existing cause, discard the finalizer's
returned error or cause, or create a self-cause.

Rollback-source selection receives both prior retained records and prior transient
evidence. Every selection failure re-proves and returns both sets; unreadable or occupied
names discovered before selection cannot disappear merely because no unique rollback source
was found. Likewise, every independent private-name attempt immediately captures the
current named leaf and any distinct held-stage identity when an otherwise ordinary exception
escapes its inner operation. A typed publication error returned by an inner stage locator or
retainer is already the authoritative evidence-bound result and is propagated unchanged; a
generic fallback must not append a second held-stage claim. Converting an ordinary exception
without rebuilding that private leaf and storing the exact exception is not a valid evidence
boundary.

No failure path invokes recursive deletion. A failed or partial stage is retained without
being treated as a trusted cache whenever a legal destination is available. If no legal
atomic move is possible, the exact transient remains reachable and the typed failure plus
integrity report identifies it for operator review.

## Result and operator visibility

Publication returns an immutable result containing:

- the verified active cache;
- zero or more retained-object records with path, closed role, device, and inode.

`DescriptionCacheMigrationResult` exposes the same retained records. The CLI prints each
retained role and path after the accepted/rejected counts. Retention is not an error: a
successful replacement exits `0` after the active output and retained previous generation
are both durably named.

The final success boundary opens and binds the active and expected `previous` generations
as one set, snapshots all five leaves of every generation, rereads and hashes the complete
set, and repeats the set-wide snapshot before returning. The same boundary snapshots both
transaction-private stage/backup names before and after that terminal read. If either
private name appears, both names are independently normalized again and success is
forbidden. Any ordinary exception from build, validation, publication, or this boundary is
converted at the publication transaction boundary only after both private names have been
given the same preservation attempt; process-control exceptions are not intercepted.

An absent stage name is not by itself proof that the held stage has been normalized. Every
stage-location proof scans the active output and every legal transaction-retained name,
separates the unique location of the held stage identity from all other current-name
evidence, and treats the stage as consumed only when exactly one such location exists. A
foreign current name never turns a uniquely located held stage into a false held-stage
transient; it remains separate current evidence. The held identity is added as transient
evidence only when no unique exact location can be proved. This same complete location proof
runs after a foreign stage leaf is retained or its retention fails, so `stage=foreign` and
`output=held-stage` cannot report the held output as missing.

On a forced-error path, the current output probe carries the held-stage identity only when
output itself is the one unique held match. If the held stage is exact at `previous` or
another legal retained name, an absent/foreign output is held-less evidence and cannot claim
the same held object a second time.

The location proof receives every already published retained record as known non-held
evidence, scans `output`, `previous`, `failed-stage`, `failed-output`, and `recovery` in one
fixed order, then repeats that complete set snapshot before returning or raising. A known
`previous=old` neither becomes a held-stage match nor blocks the clean conclusion
`output=new`. Any output or retained-name insertion, removal, replacement, or readability
change between the two snapshots forbids a clean location result. After the final snapshot,
the public-parent binding check is the last filesystem operation on the clean path; a failed
binding demotes the already captured evidence without another read.

Stage creation, durable retention, absent-output post-install proof, each private-name
normalization, and the top-level bound transaction are separate ordinary-exception evidence
boundaries. Failure while normalizing the first private name never prevents an independent
attempt on the second. Before the stage attempt begins, every record/transient/error produced
by the backup attempt becomes known stage-location evidence; one live recovery path/inode can
never be both a retained record and an unrelated transient. The aggregate typed error keeps
the exact ordinary exception from each independent attempt. Generation snapshots retain the complete `os.stat_result` required
by the existing anchored reader. Stability compares exactly device, inode, size,
modification time, change time, and mode; access time is deliberately excluded. Public
generation proofs expose those same six metadata fields plus SHA-256. Writer proofs,
snapshots, and proof comparison all use one fixed owned-inventory order: UTF-8 filename-byte
order.

Closing the held stage and publication-parent descriptors is a final evidence boundary, not
an untyped context-manager afterthought. Both descriptors are closed independently even when
the first close raises. If a typed publication error is already in flight, close failures
append controlled close context and every exact close exception in close-attempt order,
without replacing its subtype, existing cause, or retained/transient evidence. If the
transaction otherwise succeeded, any close failure becomes typed `NEEDS_CONTEXT` carrying
the last retained evidence proved before closure and every exact close exception; at most one
may additionally be the explicit cause. No close failure may turn a typed failure into a
generic `OSError`, reduce a later close fault to text, or hide the attempt to close the other
descriptor.

Retained objects are never searched automatically. Only an explicitly supplied cache
root may be loaded by batch or GUI code.

## Integrity and acceptance

The integrity workflow distinguishes transient and retained artifacts:

- stage and backup names must be zero after every successful command and every safely
  normalizable failure; an impossible normalization is a reported integrity violation,
  never a successful command;
- retained names are intentional immutable evidence and are counted separately;
- a `previous` retained directory must contain exactly the five owned cache names as direct
  regular-file leaves, with no missing name, extra entry, or nested entry, and must still
  pass complete trusted-cache validation from the bytes read through the already-held parent
  descriptor with every leaf identity unchanged before and after; an otherwise stable
  inventory violation is `invalid-previous` and exits `1`;
- an exact retained `previous` whose no-follow kind is a regular file, symlink, special
  object, or any other non-directory kind is `unsafe-object` and exits `1`; it is never
  ordinary `partial-evidence`. Only `failed-stage`, `failed-output`, and `recovery` may use
  `partial-evidence`, and symlink/special objects in those roles remain `unsafe-object`;
- partial retained roles are not required to validate as caches, but their path, role,
  size, and SHA-256 tree digest are reported;
- every retained record surfaced by publication or the CLI must still match its path by
  no-follow `(device, inode)` proof at the error/result boundary;
- no retained directory may be reused as a description source automatically.

Integrity scanning is no-follow and bounded: one regular file is limited to 64 MiB, one
retained tree to 512 MiB, 100,000 regular files, 125,000 total entries, and depth 64. The
scanner reports `oversized` instead of emitting a digest for truncated evidence. It compares
descriptor device, inode, size, modification time, change time, and mode before and after
every file read and reports `unstable` on a
change; an inaccessible sibling is `unreadable`. Symlinks and special objects are recorded
without following or reading their targets. The held publication parent also receives a
stable, sorted, no-follow snapshot of every active, retained-prefix, stage, and backup leaf
before and after the scan. Every retained directory receives a complete sorted tree snapshot
before its payload reads and another complete tree snapshot after them. After all retained
artifacts have been read, the scanner repeats a terminal whole-artifact-set round and
requires every tree state and digest to equal the first round. A `previous` cache is
validated from the exact bytes captured inside that same stable tree round, never by a
second pathname or loader read. This rejects an early retained file changed in place while a
later artifact is being scanned even when no parent-directory metadata changes.

Any relevant sibling insertion, removal, replacement, or metadata change makes the
enumeration incomplete and exits `2`; it can never yield a clean report. Exit codes are
closed: `0` is allowed only when every retained artifact is `valid-cache` or ordinary
`partial-evidence` and there is no transient or malformed artifact; `1` covers
`invalid-previous`, `unsafe-object`, `oversized`, `unstable`, `unreadable`, every transient,
and every malformed artifact; `2` covers invalid input, an unbindable active root, unstable
publication-parent enumeration, report parse failure, or report write failure.
Replacing a top-level retained sibling with another inode is therefore always a command
boundary exit `2` with no trustworthy report, even when the replacement is itself a valid
cache. Exit `1` with `unstable` is reserved for an artifact whose top-level sibling binding
remains fixed while its held file/tree contents change during a stable enumeration round.

Canonical report ordering is UTF-8 absolute-path-byte order, followed by role/reason where a
tie is possible. The complete closed reason-code set is `stage-transient`,
`backup-transient`, `malformed-stage-name`, `malformed-backup-name`,
`malformed-retained-name`, and `unreadable-transient`. An exact retained name whose leaf is
unreadable remains a retained row with validation `unreadable`, unknown kind, and null
identity; it does not use a reason code. Retained-tree depth uses the retained root as depth
`0` and each direct child as depth `1`; depth `64` is
accepted and the first entry at depth `65` is `oversized`.

Task 11 source-map and historical-output immutability checks remain unchanged.

## Compatibility

The active cache format, marker, manifest, payload hashes, source replay, batch dependency
fingerprint, and public `load_trusted_description_cache(root)` semantics do not change.
Only publication lifecycle/evidence reporting and the explicit retained-integrity action
change; extraction and trusted-cache content schemas do not.

Existing users with no retained siblings see identical load behavior. Unsupported hosts
fail closed before transaction-ID allocation or any publication filesystem mutation.

## Testing

Tests must prove:

1. a replacement succeeds without `rmtree` and retains the exact previous inode;
2. swapping a source name immediately before retention never deletes either directory;
3. first-publication rollback retains the exact failed output, leaves output absent, and
   preserves the original post-install typed subtype after successful retention;
4. ambiguous recovery returns typed `NEEDS_CONTEXT` with all reachable objects present;
5. successful commands leave no stage or backup names, while impossible normalization
   preserves the exact transient and returns `NEEDS_CONTEXT`;
6. a `previous` collision restores the old active generation, retains the new generation,
   and reports only currently re-provable retained records;
7. capture failures, including `FileExistsError` after a successful `mkdir`, normalize to
   `failed-stage` or `recovery` whenever their exact identity and a free destination can be
   proved, while only `mkdir` itself may report a collision;
8. parent and stage-leaf takeovers after successful no-follow stage-descriptor/identity
   capture and before first write leave the foreign tree byte-for-byte untouched; tests do
   not claim this guarantee for the uncloseable `mkdirat`-return-to-capture interval;
9. CLI output reports retained roles and paths;
10. public, held-parent, and held-stage loaders remain byte-for-byte equivalent;
11. mid-scan insertion or removal of a stage, backup, or retained-prefix sibling rejects the
    scan as an unstable command boundary rather than returning a clean report;
12. a `previous` move followed by parent-fsync failure preserves `output=new` and
    `previous=old` without invoking rollback;
13. held-stage and final active/previous validation reject whole-generation mutation after
    an earlier file or generation was read, including same-inode writes;
14. late insertion of either private name is independently normalized and can never return
    success, while rollback selection and recovery errors expose every prior transient only
    after a fresh current-name proof;
15. arbitrary ordinary lifecycle exceptions still run both private-name attempts, capture
    evidence for the attempt that failed, preserve each exact exception in the ordered
    identity-de-duplicated failure ledger, and return typed evidence; stage-location
    conversion preserves exact parent-proof, stage-read, foreign-retention, and
    failed-stage-retention faults rather than keeping only their filesystem rows;
16. primary, absent-output, and recovery renames that complete and then raise—including
    `FileExistsError`—are detected by two-name reproof and report the installed/live record;
17. replacement of the public parent during the last leaf reproof fails the terminal parent
    proof and demotes the last proved records without a later filesystem call;
18. retained-tree and terminal whole-set proofs reject an early retained child mutated in
    place while a later artifact is scanned, and validate `previous` from the same proof
    round;
19. an absent stage leaf is accepted only when the held stage identity remains exact at
    output or a legal retained name; otherwise the held identity remains transient evidence;
20. descriptor-close faults attempt both closes and keep every injected close exception by
    identity and close-attempt order; an in-flight typed error keeps its subtype, cause, and
    evidence, while close faults after nominal success return typed `NEEDS_CONTEXT` with the
    last proved retained evidence;
21. retained `previous` validation rejects a missing owned leaf, an extra ordinary file, or
    any nested entry as `invalid-previous`/exit `1`, while replacement of the top-level
    retained sibling remains an unstable command boundary/exit `2`;
22. a normal-return recovery move followed by source-name reacquisition preserves both the
    exact recovery record and the current source transient;
23. stage location finds the held identity at `previous`, carries an unrelated published
    `previous` separately, never adds a contradictory held output/stage transient, threads
    backup-attempt recovery evidence into the later stage proof, and rejects output changes
    between its first and terminal scans on both clean-return and forced-error paths;
24. exact retained `previous` regular-file, symlink, and special-object leaves are
    `unsafe-object`/exit `1`, never `partial-evidence`/exit `0`;
25. ordinary-exception conversion never creates `error.__cause__ is error`, never overwrites
    a pre-existing or evidence-finalization cause, keeps every exact independent failure in
    event order through its typed ledger—including initiating plus parent/identity/retention,
    primary plus sync plus final-parent-proof, rollback plus normalization faults, and bound
    validation plus its later parent-proof fault—and clean interpreter imports cover the
    complete new publication module graph in forward and reverse order;
26. separate atomic-rename-unsupported and stage-I/O-unsupported publication tests each prove
    zero UUID, descriptor-relative `mkdir`, stage-writer, no-replace-adapter, and
    exchange-adapter calls; direct support-contract tests prove that neither rejecting
    preflight invokes any transaction or rename adapter;
27. raw retention emits no phantom transient for a proved-absent destination or disappeared
    already-recovery candidate; every non-absence source, target, retained-row,
    transient-row, or locator read failure keeps both `identity=None` evidence and the exact
    `OSError` object in the ordered failure ledger;
28. low-level publication-parent `open`, parent-descriptor `fstat`, public-parent no-follow
    `stat`, and stage-writer leaf `open` wrappers each seed the exact caught `OSError` into
    `failures` in first-event order even when that same object is the explicit cause;
    end-to-end stage creation preserves the exact `fstat`/public-parent `stat` objects through
    its `parent_identity=None` and `created=False` outer branches rather than replacing them
    with aggregate typed wrappers;
29. full Task 5, repository, static, and pure-LOC gates remain green.

## Non-goals

- Automatic garbage collection or retention limits;
- deleting retained evidence during migration;
- loading retained evidence without an explicit user-selected path;
- changing source-map, historical-output, or trusted-cache content schemas.
- closing the POSIX provenance window between successful `mkdirat` and the first no-follow
  stage-descriptor/identity capture against a same-permission hostile namespace writer.

An explicit, separately designed cleanup command may be added later. It is not part of
this implementation because it would reintroduce the deletion authority intentionally
removed here.
