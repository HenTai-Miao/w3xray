# Runtime Knowledge

## Batch icon and description extraction

Run from the repository root:

```bash
uv run main.py batch MAP_DIRECTORY \
  --output OUTPUT_DIRECTORY \
  --game-data WARCRAFT_DIRECTORY
```

- Sources are scanned recursively in stable order for `.w3x`, `.w3m`, and `.w3n`.
- Processing is sequential: one map, one icon payload, and one Pillow image at a time.
- Classic client lookup order is `War3Patch.mpq`, `War3xLocal.mpq`, `War3x.mpq`, then `war3.mpq`.
- Source maps and client archives are read-only. All writes stay below the selected output root.
- An unchanged result is resumed only when it is `完整`, its size/mtime-ns/SHA-256 match, and all required reports still exist.
- `部分完成` and `受限` results are reprocessed. Failed results are retried unless `--no-retry-failed` is supplied.

The schema-v2 output root contains `批量提取汇总.tsv`, `批量提取状态.json`, `失败与重试.tsv`, `可信描述缓存.tsv`, and one SHA-addressed directory per map below `地图/`. Each map publishes complete-text, acquisition, equipment-skill, and relation-completeness reports in addition to the legacy description and icon reports.

## Real-map schema-v2 acceptance on 2026-07-15

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
- All 39 current source paths and SHA-256 values exactly match the before-run manifest.
- Version-8 fixed placements with `randomFlag=-1` are supported; the real `LT科技转职` sample now parses 345/345 units and publishes its drop, ground-item, inventory, and shop-instance relations.
- A complete classic MPQ set is no longer present locally. Final icon parity used the hash-bound `trusted-icon-cache-classic` evidence root; it cannot supply descriptions or cross-map custom assets.
