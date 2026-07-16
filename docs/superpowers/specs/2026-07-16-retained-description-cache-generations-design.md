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
recovery directories. It will atomically move every directory that is no longer the
active output into an intentional retained-evidence name and leave its bytes unchanged.

The active output remains the exact five-file owned cache defined by the parent design.
Retained evidence is a sibling of the active output, not a child of it, and is never
implicitly loaded or promoted.

## Naming and identity

Each migration allocates one cryptographically random transaction identifier. Transient
names remain:

- `.w3xray-description-cache-stage-<transaction-id>`;
- `.w3xray-description-cache-backup-<transaction-id>`.

Before returning, every surviving transient name is atomically renamed with no-replace
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
and after each move. It never overwrites an existing retained name.

## Publication flow

### First publication

1. Build the stage and validate it through the descriptor-anchored loader.
2. Atomically rename the stage to an absent output with no-replace semantics.
3. Synchronize the parent and validate the active output through the held descriptor.
4. If output proof fails, atomically retain the exact installed directory as
   `failed-output`; leave the requested output absent and return a typed error.

### Replacement

1. Validate both the stage and the existing owned output through the held parent
   descriptor.
2. Atomically exchange stage and output; the active output name is never absent.
3. Prove the new output and the displaced previous generation by their captured
   identities.
4. Atomically rename the displaced previous generation to the `previous` retained name.
5. Synchronize the parent. Successful retention is the commit point; return success with
   the new active output and retained path.

### Failure and ambiguity

If a move's postconditions cannot be proved, the publisher performs a reverse move only
when every involved name and inode is still exact. Otherwise it preserves all reachable
objects and raises `PublicationCommitContextError` containing `NEEDS_CONTEXT`.

No failure path invokes recursive deletion. A failed or partial stage is retained without
being treated as a trusted cache.

## Result and operator visibility

Publication returns an immutable result containing:

- the verified active cache;
- zero or more retained-directory paths with their closed roles.

`DescriptionCacheMigrationResult` exposes the same retained records. The CLI prints each
retained role and path after the accepted/rejected counts. Retention is not an error: a
successful replacement exits `0` after the active output and retained previous generation
are both durably named.

Retained directories are never searched automatically. Only an explicitly supplied cache
root may be loaded by batch or GUI code.

## Integrity and acceptance

The integrity workflow distinguishes transient and retained artifacts:

- stage, backup, transaction, and quarantine names must be zero after every completed
  command;
- retained names are intentional immutable evidence and are counted separately;
- a `previous` retained directory must still pass complete trusted-cache validation;
- partial retained roles are not required to validate as caches, but their path, role,
  size, and SHA-256 tree digest are reported;
- no retained directory may be reused as a description source automatically.

Task 11 source-map and historical-output immutability checks remain unchanged.

## Compatibility

The active cache format, marker, manifest, payload hashes, source replay, batch dependency
fingerprint, and public `load_trusted_description_cache(root)` semantics do not change.
Only replacement cleanup and migration result reporting change.

Existing users with no retained siblings see identical load behavior. Unsupported hosts
continue to fail closed before atomic publication.

## Testing

Tests must prove:

1. a replacement succeeds without `rmtree` and retains the exact previous inode;
2. swapping a source name immediately before retention never deletes either directory;
3. first-publication rollback retains the exact failed output and leaves output absent;
4. ambiguous recovery returns typed `NEEDS_CONTEXT` with all reachable objects present;
5. successful commands leave no stage or backup names;
6. CLI output reports retained roles and paths;
7. public and descriptor-anchored loaders remain byte-for-byte equivalent;
8. full Task 5, repository, static, and pure-LOC gates remain green.

## Non-goals

- Automatic garbage collection or retention limits;
- deleting retained evidence during migration;
- loading retained evidence without an explicit user-selected path;
- changing source-map, historical-output, or trusted-cache content schemas.

An explicit, separately designed cleanup command may be added later. It is not part of
this implementation because it would reintroduce the deletion authority intentionally
removed here.
