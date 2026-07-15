# Batch High-Availability Design

## Goal

Make batch extraction and GUI background work recoverable, verifiable, bounded, and observable without changing source maps or trusting incomplete historical output. A result is reusable only when its source, dependencies, ownership record, manifest, report schemas, counts, file sizes, and SHA-256 values all agree.

## Fixed constraints

- `/Users/zhongerbing/Desktop/Maps/**` is read-only. Tests use private fixture copies and verify source hashes before and after acceptance.
- Existing `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2` is not modified during development or acceptance.
- No map script, historical executable, or DLL payload is executed.
- Existing report filenames remain available at the batch root and inside each map directory.
- Per-map files remain below `地图/`; global transactional data remains below `.w3xray-global/`.
- No new runtime dependency is added. Python 3.14, the standard library, pytest, Ruff, and basedpyright are sufficient.
- New and substantively changed Python modules stay below 250 pure lines. `batch_runner.py` and `gui_loader_runner.py` are already in the 200–250 warning band, so new responsibilities move to focused modules.

## Per-map immutable content manifest

Every successfully built map stage contains `内容清单.json` and `.w3xray-batch-owned`.

`内容清单.json` is deterministic UTF-8 JSON with:

- manifest schema version;
- transaction/generation ID;
- source path, size, mtime-ns, and SHA-256;
- dependency fingerprint;
- map result state and all summary counts;
- every published report, original icon, PNG, and other regular artifact;
- for each artifact: normalized relative path, kind, byte size, and SHA-256;
- aggregate artifact count and byte count.

The manifest never lists itself or the ownership marker. Paths must be relative, traversal-free, unique after Unicode normalization and case folding, regular, and non-symlink. Files are hashed in bounded chunks.

The ownership marker is deterministic JSON containing the ownership schema, source SHA-256, manifest SHA-256, and transaction ID. It is valid only when all four values parse strictly and agree with the manifest. Legacy plain-digest markers are not reusable under the new batch schema.

Resume validation performs the following in order:

1. Validate state semantics and dependency fingerprint.
2. Resolve the output path through the safe-output boundary.
3. Parse and cross-check ownership and manifest identity.
4. Re-read every listed file, require exact size and SHA-256, and reject unlisted regular output files.
5. Parse the required TSV reports with `csv.reader`, verify exact headers and row widths, and reconcile icon, complete-text, relation, and incomplete-relation counts with `MapBatchResult`.

Any mismatch makes the result non-reusable and emits a stable diagnostic code. Validation never repairs a published directory in place.

## Crash-consistent per-map publication

All staged file writes flush file content with `fsync` before publication. Directory metadata is synchronized after create, link, rename, replace, restore, and cleanup where the platform supports directory synchronization. A synchronization failure is a publication failure; an old destination is restored while its backup still exists.

Each map publication uses an explicit transaction record under `地图/`:

1. `building`: create a uniquely named private stage and durable transaction record.
2. `prepared`: finish files, write and synchronize manifest and ownership marker, then record their hashes.
3. `backup_ready`: move a valid owned prior destination to a transaction-bound backup and synchronize the parent.
4. `destination_ready`: move the prepared stage to the destination and synchronize the parent.
5. `committed`: remove the backup and transaction record only after the destination validates.

Startup recovery parses only strict transaction records whose stage, backup, and destination names match the transaction ID and stay immediately below `地图/`. Recovery chooses one deterministic outcome:

- keep a valid committed destination and remove matching owned leftovers;
- finish publishing a valid prepared stage when no valid destination exists;
- restore a valid owned backup when publication did not complete;
- leave unprovable paths untouched and report a recovery diagnostic.

Rename, `fsync`, ENOSPC, cleanup, and process-interruption fault tests cover every transition. Recovery is idempotent.

## Transactional global generations

The authoritative global snapshot lives at `.w3xray-global/generations/<generation-id>/` and contains:

- `批量提取汇总.tsv`;
- `批量提取状态.json`;
- `失败与重试.tsv`;
- `可信描述缓存.tsv`;
- `批量诊断.jsonl`;
- `全局清单.json` with size and SHA-256 for the five files.

A generation is staged, synchronized, renamed into `generations/`, validated, and then selected through one atomically replaced and synchronized `.w3xray-global/current.json` pointer. Resume and automatic cache loading use only the validated pointed generation. Root-level report files remain compatibility mirrors written after the authoritative commit; a crash between mirrors cannot corrupt resume state.

## Strict state, dependency fingerprint, and safe reuse

The batch state schema is incremented. Parsing rejects:

- malformed or non-lowercase 64-character SHA-256 values;
- negative sizes, mtimes, durations, counters, memory, or byte totals;
- duplicate source identities or case-folded source paths;
- duplicate count labels or negative count values;
- unsafe output paths;
- impossible state/stage/output combinations;
- manifest/dependency hashes with invalid syntax.

The dependency fingerprint hashes a deterministic record containing:

- batch schema and tool version;
- source SHA-256;
- normalized batch options that affect extraction;
- game-data kind and bounded identity evidence: classic MPQ stats, CASC `.build.info` hash plus data/index stats, trusted-cache manifests, or extracted-directory path/size/mtime inventory;
- the validated trusted-description-cache SHA-256.

`完整`, `部分完成`, and `受限` results are reusable when source, dependencies, and complete publication validation match. Persistent evidence gaps therefore do not force another extraction. `失败` keeps the existing `--no-retry-failed` behavior. Dependency changes force reprocessing.

Every checkpoint merges newly handled results with still-unvisited valid previous entries for sources that remain in the scan. Interruption cannot truncate the tail of a prior state.

Automatic description-cache discovery accepts a report only after its entire map publication passes manifest validation. Each cache entry records the source manifest SHA-256. The standalone cache is loaded automatically only from a validated global generation; a user-selected cache remains an explicit user input and is parsed strictly.

## Cancellation, timeout, disk, and memory boundaries

The batch runner accepts a cancellation signal and a progress callback. The CLI installs a two-stage SIGINT handler: the first signal requests graceful cancellation, publishes an explicit `已取消` result/checkpoint, and terminates the active child; a second signal raises `KeyboardInterrupt`.

Normal CLI map processing runs in a spawn-compatible child process. The parent:

- enforces a positive per-map timeout;
- polls cancellation without sleeping unboundedly;
- terminates and, if needed, kills and reaps the child;
- converts timeout, child crash, explicit `MemoryError`, and missing result payloads into typed failed/cancelled outcomes;
- optionally applies a per-map address-space limit on platforms supporting `resource.setrlimit`.

The direct Python API may explicitly disable isolation for deterministic unit tests. The CLI does not disable it.

Before each map, disk preflight requires configurable reserve bytes plus a conservative source-size expansion budget. ENOSPC during writing leaves the old publication valid or leaves no new destination. Peak RSS, elapsed time, published bytes, action (`processed`, `reused`, `failed`, `cancelled`), diagnostic code, completed/total count, and ETA are exposed through progress and JSONL diagnostics. Memory collection is best effort and reports zero with a diagnostic when unsupported.

## Unified GUI worker lifecycle

One `GuiWorkerRegistry` owns all application-level daemon workers: map/campaign loading, object filtering, current-map discovery/snapshot work, source-directory scans, external-save analysis, exports, and game-data browser opening.

Each worker receives an immutable ticket with a group, generation, and cancellation event. Replaceable jobs cancel older tickets in the same group. A worker never calls Tk: it can only append a guarded result to a lock-protected host queue. One Tk-main-thread `after` poll drains that queue every 20 milliseconds and checks the ticket again before delivery. Resource-bearing stale or late results execute their cleanup callback instead of touching Tk.

Shutdown proceeds in this order:

1. mark the registry stopped and signal every ticket;
2. cancel all Tk poll callbacks and invalidate subsystem generations;
3. drain queued resource-bearing payloads;
4. join workers only until one shared monotonic deadline;
5. log still-running daemon names and allow the window to close;
6. late workers perform cleanup and cannot enqueue or call Tk.

No GUI close path waits indefinitely. Loader, filter, current-map, source scan, external analysis, export, and CASC-open lifecycle tests cover normal completion, replacement, shutdown timeout, and late cleanup.

## Quality gates and cross-platform acceptance

`pyproject.toml` adds pinned development ranges for Ruff and basedpyright plus explicit project configuration. A cross-platform `w3xray-quality` entry point runs:

- `ruff check` on the maintained strict path set;
- `ruff format --check` on the same set;
- `basedpyright --level error` on the same set.

The strict path set contains every module and test changed by this feature and is stored once in Python, so POSIX and Windows workflows cannot drift. Historical repository-wide findings remain documented and are not silently reformatted in this change.

macOS/Linux packaging, Windows packaging, and real-Windows CASC workflows run the quality gate before tests. Packaged acceptance adds a private-copy batch fixture lane that validates manifests, performs a second reusable run, checks no transaction leftovers, and confirms the fixture SHA-256 is unchanged.

Unit/integration coverage includes manifest tampering, state corruption, dependency changes, partial-result reuse, checkpoint-tail preservation, transaction fault injection, timeout/cancellation, disk exhaustion, child crash/OOM, bounded GUI shutdown, and repeated small-fixture soak runs. Final validation runs focused tests, the full test suite, quality gates, packaged acceptance where locally available, and source-hash checks.

## Compatibility and migration

- The new state/manifest schema intentionally invalidates legacy resumability. Existing files are never deleted merely because they are legacy.
- A new run may replace only a destination proven owned by the same source digest; otherwise it chooses the content-addressed destination or fails safely.
- Root-level reports remain readable by existing users, but `.w3xray-global/current.json` is the sole authoritative resume pointer.
- Public `MapData`, object, relation, description, and report data contracts are unchanged.
- The source map inventory and its SHA-256 values must be identical before and after every real-map acceptance.
