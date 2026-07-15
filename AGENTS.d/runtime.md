# Runtime Knowledge

## Schema-4 revision-4 resilient batch extraction

Run from the repository root:

```bash
uv run main.py batch MAP_DIRECTORY \
  --output OUTPUT_DIRECTORY \
  --game-data WARCRAFT_DIRECTORY
```

- Sources are scanned recursively in stable order for `.w3x`, `.w3m`, and `.w3n`.
- Normal CLI processing isolates one map at a time in a spawned child. The default per-map timeout is 900 seconds; the default free-space reserve is 536,870,912 bytes; the address-space limit is disabled unless `--max-memory-bytes` is supplied.
- Optional boundaries are `--map-timeout-seconds`, `--max-memory-bytes`, and `--minimum-free-bytes`. The first Ctrl-C requests a checkpointed graceful cancellation; a second Ctrl-C exits immediately with code 130.
- Classic client lookup order is `War3Patch.mpq`, `War3xLocal.mpq`, `War3x.mpq`, then `war3.mpq`.
- Source maps and client archives are read-only. All writes stay below the selected output root.
- One non-blocking cross-process lease owns the output root for recovery, checkpoints, final publication, and retirement; a concurrent writer fails before processing.
- The current 39-map schema-4 publication target is `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4`; never use the historical `map-extract-output-v2` as a new-run destination.
- `完整`, `部分完成`, and `受限` results are reused only when source identity, dependency fingerprint, ownership marker, content manifest, every file hash, report schema, and reconciled counts all match. Failed results are retried unless `--no-retry-failed` is supplied.

Each map directory below `地图/` contains `内容清单.json`, `.w3xray-batch-owned`, the legacy reports, complete-text/acquisition/equipment-skill reports, and icon artifacts. Map publication uses transaction-bound stage and backup directories; startup recovery keeps a validated destination, finishes a validated prepared stage, or restores a validated owned backup, while leaving unprovable paths untouched.

After a full batch with no failed or cancelled result publishes its final authoritative generation, the runner retires obsolete display-name directories only when they are direct children of `地图/`, are not referenced by the authority, pass the complete ownership/manifest/report/file validation, and bind the same source SHA-256 as a current result. Unowned paths, foreign-source publications, symlinks, private transaction paths, and interrupted batches are never retired by this pass.

The only resume authority is `.w3xray-global/current.json`, which selects a validated immutable generation below `.w3xray-global/generations/`. A generation binds `批量提取汇总.tsv`, `批量提取状态.json`, `失败与重试.tsv`, `可信描述缓存.tsv`, and `批量诊断.jsonl` through `全局清单.json`. Root reports are compatibility mirrors, not resume state. Legacy root-only batch state is ignored but not deleted.

## Local high-availability acceptance on 2026-07-15

- `uv run main.py acceptance ... --repeat 5` completed with overall status `pass`.
- `batch_publication` validated the source SHA-256 and map manifest, observed `processed` then `reused`, and found zero stage/backup/transaction leftovers.
- `repeat_load` completed five stable loads with `stable_total=18`; map load, campaign switch, 71-file knowledge-pack export, and all 10 GUI tabs passed.
- The existing `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2/` was not modified.

## Current schema-4 real-map publication on 2026-07-15

- Current source root: `/Users/zhongerbing/Desktop/Maps/`.
- Current inventory: 39 maps, 4,227,067,802 source bytes.
- Published output: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v4/`, about 5.7 GiB.
- Result states: 1 `完整`, 38 `部分完成`, 0 `受限`, 0 `失败`.
- Objects: 109,637 summary objects and 700,979 lossless text-evidence rows.
- Text states: 285,565 map values, 0 live-client fills, 0 trusted-cache fills, 857 explicit empty values, 7,000 author-undefined rows, 351,923 source-unavailable rows, and 55,634 conflict variants.
- Full-text audit: the longest raw value is 6,363 characters; 341 rows contain physical newlines and 128,340 rows retain Warcraft color-code evidence.
- The schema-4 trusted-description cache is empty because the local evidence root is icon-only. The legacy v2 cache has no source-manifest binding and is intentionally rejected rather than treated as verified text evidence.
- Relations: 13,442 total — 135 unit drops, 221 destructable drops, 4,067 shop sales, 1,078 shop makes, 294 recipes, 277 ground placements, 39 inventories, 2,255 script rewards, 3,449 item abilities, and 1,627 cooldown abilities.
- Relation evidence: 12,836 confirmed and 606 inferred; completeness is 7,974 complete, 4,883 partial, 585 unresolved, and 0 conflicts in this corpus.
- Icon records: 32,690 named plus 46,388 anonymous; all 79,078 logical exports wrote an original and PNG with zero decode/write failures.
- Physical files: 78,916 unique originals and 78,916 unique PNGs. The 162-record difference is `.tga`/`.blp` references resolving to the same proven `.blp` and intentionally reusing one file.
- Unresolved named references: 9,682. These are recorded static-evidence gaps, not failures of already exported files.
- The revision-4 clean run processed 39/39 results in 566.45 seconds with an observed 783.98 MiB peak resident set size. The immediate validation run reused 39/39 in 39.77 seconds.
- Campaign children inherit shared objects through exact `(category, rawcode)` identities, so equal rawcodes in different object categories cannot cross-resolve.
- After high-availability acceptance, all 39 source paths, sizes, mtime-ns values, and SHA-256 values exactly matched the saved before-run manifest byte for byte; the historical v2 tree also retained the same 158,226 files and content+metadata Merkle SHA-256.
- The final authority contains exactly 39 ordinary map directories and zero stage/backup/transaction/quarantine leftovers.
- Version-8 fixed placements with `randomFlag=-1` are supported; the real `LT科技转职` sample now parses 345/345 units and publishes its drop, ground-item, inventory, and shop-instance relations.
- A complete classic MPQ set is no longer present locally. Final icon parity used the hash-bound `trusted-icon-cache-classic` evidence root; it cannot supply descriptions or cross-map custom assets.
