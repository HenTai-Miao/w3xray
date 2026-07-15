# Runtime Knowledge

## Schema-3 resilient batch extraction

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
- `完整`, `部分完成`, and `受限` results are reused only when source identity, dependency fingerprint, ownership marker, content manifest, every file hash, report schema, and reconciled counts all match. Failed results are retried unless `--no-retry-failed` is supplied.

Each map directory below `地图/` contains `内容清单.json`, `.w3xray-batch-owned`, the legacy reports, complete-text/acquisition/equipment-skill reports, and icon artifacts. Map publication uses transaction-bound stage and backup directories; startup recovery keeps a validated destination, finishes a validated prepared stage, or restores a validated owned backup, while leaving unprovable paths untouched.

The only resume authority is `.w3xray-global/current.json`, which selects a validated immutable generation below `.w3xray-global/generations/`. A generation binds `批量提取汇总.tsv`, `批量提取状态.json`, `失败与重试.tsv`, `可信描述缓存.tsv`, and `批量诊断.jsonl` through `全局清单.json`. Root reports are compatibility mirrors, not resume state. Legacy root-only batch state is ignored but not deleted.

## Local high-availability acceptance on 2026-07-15

- `uv run main.py acceptance ... --repeat 5 --no-gui` completed with overall status `pass`.
- `batch_publication` validated the source SHA-256 and map manifest, observed `processed` then `reused`, and found zero stage/backup/transaction leftovers.
- `repeat_load` completed five stable loads with `stable_total=18`; map load, campaign switch, and 71-file knowledge-pack export passed.
- The existing `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2/` was not modified.

## Existing real-map content baseline on 2026-07-15

- Current source root: `/Users/zhongerbing/Desktop/Maps/`.
- Current inventory: 39 maps, 4,227,067,802 source bytes.
- Published output: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output-v2/`, about 5.7 GiB.
- Result states: 1 `完整`, 38 `部分完成`, 0 `受限`, 0 `失败`.
- Objects: 122,075 summary objects and 766,396 lossless text-evidence rows.
- Text states: 284,478 map values, 0 live-client fills, 56,972 trusted-cache fills, 644 explicit empty values, 0 author-undefined rows, 369,006 source-unavailable rows, and 55,296 conflict variants.
- Trusted description cache: 3,043 entries, 0 conflicts, 0 diagnostics; repeated publication is byte-stable.
- Relations: 13,047 total — 135 unit drops, 221 destructable drops, 3,962 shop sales, 1,063 shop makes, 294 recipes, 277 ground placements, 39 inventories, 2,255 script rewards, 3,174 item abilities, and 1,627 cooldown abilities.
- Icon records: 32,690 named plus 46,388 anonymous; all 79,078 logical exports wrote an original and PNG with zero decode/write failures.
- Physical files: 78,916 unique originals and 78,916 unique PNGs. The 162-record difference is `.tga`/`.blp` references resolving to the same proven `.blp` and intentionally reusing one file.
- Unresolved named references: 9,682. These are recorded static-evidence gaps, not failures of already exported files.
- The final 39-map run took 464.02 seconds with an 887,095,296-byte maximum resident set size.
- After high-availability acceptance, all 39 source paths, sizes, mtime-ns values, and SHA-256 values exactly matched the saved before-run manifest byte for byte.
- Version-8 fixed placements with `randomFlag=-1` are supported; the real `LT科技转职` sample now parses 345/345 units and publishes its drop, ground-item, inventory, and shop-instance relations.
- A complete classic MPQ set is no longer present locally. Final icon parity used the hash-bound `trusted-icon-cache-classic` evidence root; it cannot supply descriptions or cross-map custom assets.
