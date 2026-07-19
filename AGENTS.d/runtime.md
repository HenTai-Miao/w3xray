# Runtime Knowledge

## Schema-5 revision-5 workflow

Run from the repository root with explicit paths:

```bash
uv run main.py description-cache migrate \
  --legacy-output <schema-1-root> \
  --legacy-cache <schema-2-cache.tsv> \
  --output <owned-cache-root>

uv run main.py batch <maps-root> \
  --output <v5-root> \
  --game-data <client-or-trusted-icon-root> \
  --description-cache <owned-cache-root>
```

- Sources are scanned recursively in stable order for `.w3x`, `.w3m`, and `.w3n`.
- Source maps, legacy outputs/caches, and game-data roots are read-only. All writes stay below the selected new output/cache root.
- Normal batch processing isolates one map at a time in a spawned child. Defaults: 900-second timeout, 536,870,912-byte free-space reserve, and no address-space limit unless `--max-memory-bytes` is supplied.
- Optional boundaries are `--map-timeout-seconds`, `--max-memory-bytes`, and `--minimum-free-bytes`. First Ctrl-C requests a checkpointed cancellation; second Ctrl-C exits with 130.
- Reuse requires exact source identity, dependency fingerprint, ownership marker, content manifest, file hashes, report schemas, and reconciled evidence counters. Failed results retry unless `--no-retry-failed` is supplied.

## Integrity commands

```bash
uv run main.py integrity snapshot \
  --root maps=<maps-root> \
  --root legacy-v1=<root> \
  --root legacy-v2=<root> \
  --root legacy-v4=<root> \
  --output <before.json>
uv run main.py integrity verify --snapshot <before.json>
uv run main.py integrity retained-cache \
  --active-root <owned-cache-root> \
  --output <retained-cache-report.json>
```

- Snapshot roots must be absolute after normalization and bind as physically
  nonoverlapping no-follow directories. All root descriptors are held through
  traversal and report publication. Real case/Unicode aliases and physical
  ancestor relationships are rejected by held identity, while distinct
  spellings on a case-sensitive or normalization-preserving filesystem remain
  valid independent paths.
- Verification returns 0 for equality, 1 for content/metadata differences, and 2 for request, parse, unsafe-root, or I/O boundaries.
- Retained-cache inspection holds every no-follow ancestry descriptor plus the
  publication parent and active-root descriptors through both sibling scans
  and report-publication proof; required descriptor capabilities and flags
  fail closed as code 2.
- Retained `previous`, failed-stage, failed-output, and recovery evidence is reported separately from stage/backup transient violations. Retained objects are never automatically loaded as description sources and are never deleted by inspection.
- An integrity output that already exists is atomically exchanged with the new
  report. The new report keeps the requested path; the displaced inode moves to
  `.w3xray-integrity-history/<sha256(output leaf)>/<generation-id>/report.json`.
  Its exact two-file generation also contains `历史清单.json`, which binds
  schema, generation ID, original output leaf, size, and SHA-256.
- History roots, buckets, stages, and finalized generations are descriptor-held
  mode-0700 directories outside protected identities. Every binding and both
  history files are re-proved around synchronization. Finalized generations are
  append-only and never automatically deleted or overwritten; an uncertain
  failure retains the provable recovery object instead of deleting evidence.
- The history-root leaf and its exact-parent filesystem aliases are reserved.
  Before exchange, both participating file identities are re-proved and an
  owned failed stage is cleaned through identity gating. Once exchange state is
  uncertain, automatic cleanup stops and every recoverable object is retained.
- The generic safe-output writer retains plain atomic-replacement semantics for
  maps and resources and never creates integrity-report history on its own.
- Snapshot/report labels and all external path values must encode as strict
  UTF-8 before filesystem binding, sorting, hashing, or publication. Invalid
  external Unicode is a command-boundary exit 2.

## Protected roots and new outputs

Do not inspect or mutate the real-data roots during ordinary development. Task 11 alone owns opt-in real-data acceptance:

- Read-only maps: `/Users/zhongerbing/Desktop/Maps`.
- Read-only historical evidence: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output`, `map-extract-output-v2`, and `map-extract-output-v4`.
- Read-only icon evidence: `/Users/zhongerbing/Documents/xm/war3_xg/trusted-icon-cache-classic`.
- New external outputs: `trusted-description-cache-v5`, `map-extract-output-v5`, and `schema5-*-integrity.json` below `/Users/zhongerbing/Documents/xm/war3_xg/`.

Development and Task 10 acceptance use only `tmp_path`/system-temp fixtures. Generated outputs never belong in the repository.

## Publication and reports

Each map publication requires `内容清单.json`, `.w3xray-batch-owned`, and all reports in `REQUIRED_MAP_REPORTS`, including `图标未解析.tsv`, `对象完整描述.tsv`, both relation TSVs, and `关系完整性.txt`.

Each immutable global generation binds the ordinary summary/state/retry/cache/diagnostic payloads plus `图标缺口汇总.tsv`, `图标候选绑定.tsv`, `图标缺口统计.txt`, and `三轴状态汇总.tsv` through `全局清单.json`. Root copies are compatibility mirrors; `.w3xray-global/current.json` selecting a validated generation is the only resume authority.

`图标候选绑定.tsv` is non-authoritative suggestion evidence and every row remains unadopted. `三轴状态汇总.tsv` keeps publication result, archive integrity, and knowledge completeness independent. Current-text counters use only `是否当前值=是`; all text evidence remains in the report and GUI “全部证据” view.

Retirement/recovery may act only on direct owned children whose identities, manifests, report bytes, and source bindings are re-proved under the output lease. Unknown paths, symlinks, foreign sources, private transaction paths, and unprovable objects remain untouched.
