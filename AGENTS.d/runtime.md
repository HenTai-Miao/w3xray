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

- Source root: `/Volumes/zhongerbing/Program Files (x86)/Warcraft III/Warcraft III Frozen Throne/Maps/`.
- Current inventory: 38 maps, 4,216,980,827 source bytes.
- Published output: `/Users/zhongerbing/Documents/xm/war3_xg/map-extract-output/`, about 5.6 GiB.
- Result states: 1 `完整`, 37 `部分完成`, 0 `受限`, 0 `失败`.
- Objects: 133,232 unique objects and 136,787 description rows.
- Description rows: 77,427 map values, 23,895 client fills, 61 explicit empty values, and 35,404 source-missing values.
- Icon records: 32,397 named plus 46,137 anonymous; all 78,534 logical exports wrote an original and PNG with zero decode/write failures.
- Physical files: 78,372 unique originals and 78,372 unique PNGs. The 162-record difference is `.tga`/`.blp` references resolving to the same proven `.blp` and intentionally reusing one file.
- Unresolved named references: 9,679. These are recorded static-evidence gaps, not failures of already exported files.
- Corrected full rerun: 503.25 seconds wall time, 1,002,749,952-byte maximum resident set size.
- Before/after source fingerprint manifests were byte-identical with SHA-256 `a81ab91345f94efb951d561d36a29e2d7e0cc75d204b200aa28355100df8e927`.
