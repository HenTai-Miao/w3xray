# Real map fixtures

## `war3net-map-script-builder.w3x`

- Source: <https://github.com/Drake53/War3Net/blob/11ff1ed081e02a91fc960ba653b0ee91e9b498b0/tests/War3Net.TestTools.UnitTesting/TestData/Maps/MapScriptBuilderTestMap1.w3x>
- Commit: `11ff1ed081e02a91fc960ba653b0ee91e9b498b0`
- Original map SHA256: `c405bf8750fc72fc2c21a2a69b37a4703bf30f720a378bb70bf8a03275fdc415`
- Extracted WTG SHA256: `6b64cb88e25da01163130f0bd97680dc743bd826fa1b73c590e16278cb719503`
- Extraction: companion `war3map.wtg` fixture was extracted from this map archive and stored as `tests/fixtures/wtg/reforged-war3net-map-script-builder.wtg`
- Release scenario: `tests/test_static_extraction_workflow.py` loads this real map with the pinned TriggerData/TriggerStrings fixtures and a parsed external listfile, then verifies localized ECA, listfile diagnostics, resources, map/object IDs, completeness output, and immutable export behavior.
- License: MIT, copied in `tests/fixtures/licenses/War3Net-MIT.txt`
