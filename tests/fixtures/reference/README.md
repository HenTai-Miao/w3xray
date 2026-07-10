# Reference container fixtures

These fixtures replace machine-local Warcraft III paths in the mandatory test suite.
They are real MPQ v1 containers produced by the independent StormLib writer, not byte
layouts assembled by the parser under test.

## Inputs

- `war3net-map-script-builder.w3x`: War3Net test map, MIT, documented in
  `../maps/README.md`.
- `AbilityDataSmall.slk`: `inwc3/wc3libs` test data at commit
  `ac41f780a5e2dfc35310be4ed3267f23ab3fea44`, Apache-2.0, source SHA256
  `e14da5dfc2e744d819e9271534df1f659fc87b5eb068de7866a15bce3650ffe8`.
- `ExampleMap133.w3x`: War3Net test map at commit
  `11ff1ed081e02a91fc960ba653b0ee91e9b498b0`, source SHA256
  `8d0c61a5de6b74d92a592b74d835993636ebddce1e62c77ad726e0038888081c`;
  its real `war3map.w3a` becomes the campaign-level shared object table.
- StormLib commit `11db37739685f6421960109dcdb1485ade294d0b`, MIT.

License copies are stored in `../licenses/`.

## Outputs

- `stormlib-slk-map.w3x`: the War3Net map with the real wc3libs
  `Units/AbilityData.slk` added through `SFileAddFileEx`.
- `stormlib-campaign.w3n`: a campaign MPQ containing the SLK map as
  `Maps/Chapter1.w3x` and a real `war3campaign.w3a` shared object table.
- `stormlib-huffman-map.w3x`: an MPQ whose `war3map.j` sectors were encoded by
  StormLib with `MPQ_COMPRESSION_HUFFMANN`.

`tools/build_reference_fixtures.cpp` is the exact generator. Build it against the
pinned StormLib source and pass the six paths shown by its usage output.

## Recorded SHA256

The test suite asserts these hashes so accidental fixture replacement cannot
silently change the acceptance baseline:

```text
e14da5dfc2e744d819e9271534df1f659fc87b5eb068de7866a15bce3650ffe8  AbilityDataSmall.slk
eee3f01c2dbe16a22913b4a621780452dc2febe0557a97c54479e8742ec73b9f  stormlib-slk-map.w3x
617ccc0239e9c919edd4f6cce20b56e15e490ba466b661a9edba60623b68e317  stormlib-campaign.w3n
c6b04fce2ecdb7c7a5701c26bb3e91c3f1c5b911974654ae4514775e48c43a29  stormlib-huffman-map.w3x
```
