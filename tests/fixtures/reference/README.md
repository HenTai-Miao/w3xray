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

## StormLib 9.25 compression fixtures

The four `stormlib-compression-*.bin` files are deterministic sector-level
fixtures produced by the official `ladislav-zezula/StormLib` `v9.25` tag at
commit `28c9b4be3f23c6b3a5ff55cacac7dbe5b9cdc4fc`. The pinned source license is
MIT; the durable copy is `tests/fixtures/licenses/StormLib-MIT.txt`. These files are a
StormLib 9.25 compatibility baseline; a newer StormLib release is not fixture
truth.

Build the generator against the pinned static library:

```sh
clang++ -std=c++17 -Wall -Wextra -Werror -pedantic \
  -I"${TMPDIR:-/tmp}/codex-stormlib-925-task6/src" \
  tools/build_compression_fixtures.cpp \
  "${TMPDIR:-/tmp}/codex-stormlib-925-task6/xcode-derived/Build/Products/Release/libStormLib.a" \
  -lz -lbz2 -o /tmp/build_compression_fixtures
/tmp/build_compression_fixtures tests/fixtures/reference
```

The generator source SHA256 is
`1678fff14bc65df8ff274cfe7ac24ba239a7dbe920a0e8feeca3d30a0f580f74`.
It calls public `SCompCompress` and verifies the payloads through StormLib:
`SCompDecompress` for masks `0x41`, `0x81`, and `0x22`; v9.25 requires the
public `SCompDecompress2` entry point for LZMA `0x12`, because
`SCompDecompress` asserts on that marker. ADPCM expected payloads are
StormLib's lossy PCM output, rather than the input PCM.

Each file begins with the 16-byte little-endian struct `<4sIII>`:
`b"W3CF"`, requested compression mask, compressed length, expected length.
The body concatenates the exact `SCompCompress` bytes (including its marker)
and the exact StormLib decompression output.

| Fixture | Deterministic input | Requested / actual mask | Compressed / expected bytes |
|---|---|---:|---:|
| `stormlib-compression-huffman-adpcm-mono.bin` | 4096 little-endian signed-16 mono samples from a modular saw/bend waveform; SHA256 `643395f77435f6fe799bc749a5ab3ca500c6cbe64c8f3046d486429c6cca188c` | `0x41` / `0x41` | 2727 / 8192 |
| `stormlib-compression-huffman-adpcm-stereo.bin` | 4096 interleaved little-endian signed-16 stereo frames from independent modular waveforms; SHA256 `5d1fcbe23177680a629dabf3be803fa798687a17285c50836c3beabd0029d296` | `0x81` / `0x81` | 5306 / 16384 |
| `stormlib-compression-zlib-sparse.bin` | 16384 bytes of sparse zero-filled data with repeated text, block counters, and nonzero sentinels; SHA256 `cf841c47c4f453f9c4dc314a67bb1c2575e0756b1d1878188e76a395d48d825c` | `0x22` / `0x22` | 156 / 16384 |
| `stormlib-compression-lzma.bin` | 16384 bytes of a repeated text pattern with deterministic byte perturbations; SHA256 `1e2aa0a9fda31fe9e5d2e020f3bddca05a49063b0175d8002c99ffbba3cb8960` | `0x12` / `0x12` | 915 / 16384 |

```text
f0350d3b198d3ffc9670ce0a327958ba4ac3b93a8a326311ae872308725067aa  stormlib-compression-huffman-adpcm-mono.bin
aa56bc2f5bab65d1674a5763213b05264cdde04e6e4fcc25117ee09ebdf6c468  huffman-adpcm-mono.compressed
772df6e165e5239add5381f7f044d43f19639569f0b72409263f7284ae4421ee  huffman-adpcm-mono.expected
d9ee9241b07e3a083d1f3d7b8050494f464e9cfd8b3cf91c0488d2c3cda861c1  stormlib-compression-huffman-adpcm-stereo.bin
23671f877139231aa7d4cdd3804fae1f35f6ce7812c1d20a97b534e3a2148dd4  huffman-adpcm-stereo.compressed
47f2976e70ef5f6b9308e8eb959d1f9b61c82482e006973eda202c403ddd59ca  huffman-adpcm-stereo.expected
f4bac05b014054278e686c26af2e7a94654cc718693d9c6ae89da9e4948f81b3  stormlib-compression-zlib-sparse.bin
e24878ebe0e4b0ed8aec74a02c044b44b224be810c8fb9c414842aff141a29ba  zlib-sparse.compressed
cf841c47c4f453f9c4dc314a67bb1c2575e0756b1d1878188e76a395d48d825c  zlib-sparse.expected
085b7d6d8c036bbb8feb83f518ea51927970b7a6803ef2549711f981ba5591d3  stormlib-compression-lzma.bin
d8f1b5609162d7a42517d0b519b279afe68709f591ec4c08e1c409ecca218eb6  lzma.compressed
1e2aa0a9fda31fe9e5d2e020f3bddca05a49063b0175d8002c99ffbba3cb8960  lzma.expected
```
