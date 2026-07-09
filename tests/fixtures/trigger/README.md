This directory vendors direct copies of Warcraft III trigger metadata from
Crainax/War3Lib commit `03cc4765f6b5e262c0e9d6ed9f36e1f3f12c77bf`
([repo](https://github.com/Crainax/War3Lib), Apache-2.0).

Files:
- `TriggerData.txt`
  - Source: `https://raw.githubusercontent.com/Crainax/War3Lib/03cc4765f6b5e262c0e9d6ed9f36e1f3f12c77bf/fdf/TriggerData.txt`
  - SHA256: `e017e7caf50bc1e2e5426d7cbbd5710c78cea360151cdccbfa0ab2f1fc7f233b`
- `TriggerStrings.txt`
  - Source: `https://raw.githubusercontent.com/Crainax/War3Lib/03cc4765f6b5e262c0e9d6ed9f36e1f3f12c77bf/fdf/TriggerStrings.txt`
  - SHA256: `1f926154476c4674b5333e3c418ce65b3f724a2440216206285137c29ed06852`

Copy method:
- Mechanically copied with `cp` from the verified local source files under
  `/tmp/codex-w3xray-sources-20260710/`.
- No normalization, filtering, or line rewriting was applied.

Coverage notes:
- `tests/test_trigger_schema.py` asserts the real `DisplayTextToForce`
  signature from `TriggerData.txt`.
- The same test asserts that `TriggerStrings.txt` contributes the localized
  duplicate-key display records for `DisplayTextToForce`.
- `TriggerStrings.txt` intentionally contains repeated keys such as
  `MapInitializationEvent` and `DisplayTextToForce`; parser tests rely on
  preserving those ordered records instead of collapsing them into a dict.
