# Real WTG fixtures

These binary fixtures are copied unmodified from pinned upstream test assets.

## `classic-wc3libs-war3map.wtg`

- Source: <https://github.com/inwc3/wc3libs/blob/ac41f780a5e2dfc35310be4ed3267f23ab3fea44/src/test/resources/wc3data/WTG/war3map.wtg>
- Commit: `ac41f780a5e2dfc35310be4ed3267f23ab3fea44`
- Original map hash: not applicable; upstream fixture is a standalone `war3map.wtg`
- WTG SHA256: `c3398add7e0e51b66300629f152d190d80e00a4aecb6c64e07b81f3963185cb8`
- Extraction: direct copy of upstream standalone WTG fixture
- License: Apache-2.0, copied in `tests/fixtures/licenses/wc3libs-Apache-2.0.txt`

## `reforged-war3net-map-script-builder.wtg`

- Source map: <https://github.com/Drake53/War3Net/blob/11ff1ed081e02a91fc960ba653b0ee91e9b498b0/tests/War3Net.TestTools.UnitTesting/TestData/Maps/MapScriptBuilderTestMap1.w3x>
- Commit: `11ff1ed081e02a91fc960ba653b0ee91e9b498b0`
- Original map SHA256: `c405bf8750fc72fc2c21a2a69b37a4703bf30f720a378bb70bf8a03275fdc415`
- Extracted WTG SHA256: `6b64cb88e25da01163130f0bd97680dc743bd826fa1b73c590e16278cb719503`
- Extraction: `war3map.wtg` extracted from the pinned `MapScriptBuilderTestMap1.w3x`
- License: MIT, copied in `tests/fixtures/licenses/War3Net-MIT.txt`
