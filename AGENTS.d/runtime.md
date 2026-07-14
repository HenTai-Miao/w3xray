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

The output root contains `批量提取汇总.tsv`, `批量提取状态.json`, `失败与重试.tsv`, and one SHA-addressed directory per map below `地图/`.

## Real-map acceptance on 2026-07-14

- Current source root: `/Users/zhongerbing/Desktop/Maps/`.
- Current inventory: 39 maps, 4,227,067,802 source bytes.
- Published output: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output/`, about 5.6 GiB.
- Result states: 1 `完整`, 38 `部分完成`, 0 `受限`, 0 `失败`.
- Objects: 135,001 unique objects and 139,440 description rows.
- Description rows: 78,744 map values, 23,895 client fills, 71 explicit empty values, and 36,730 source-missing values.
- Icon records: 32,690 named plus 46,388 anonymous; all 79,078 logical exports wrote an original and PNG with zero decode/write failures.
- Physical files: 78,916 unique originals and 78,916 unique PNGs. The 162-record difference is `.tga`/`.blp` references resolving to the same proven `.blp` and intentionally reusing one file.
- Unresolved named references: 9,682. These are recorded static-evidence gaps, not failures of already exported files.
- The original 38-map corrected run took 503.25 seconds with a 1,002,749,952-byte maximum resident set size; map 039 was published incrementally in 5.456 seconds.
- All 39 current sources match the persisted SHA-256 and byte-size set. The 38 copied legacy maps have new paths and `mtime_ns`; map 039 retains its exact current path and metadata.
- A complete classic MPQ set is no longer present locally. Map 039 used the existing verified icon output as a read-only icon cache, so its client description-fill count is zero and its result remains explicitly `部分完成`.
