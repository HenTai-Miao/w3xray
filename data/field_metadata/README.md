# Offline field metadata inputs

These files are generator inputs. Runtime code only imports the generated
`gametool/field_meta.py`; packaging does not need this directory. None of these
files establish the current game's object values, installed version or map
contents.

`legacy-0.9.0.json` preserves all five tables from the project's 0.9.0 generated
module: 1,446 labels, 1,560 types, 709 applicability entries, 1,105 bounds and 727
constants. Its origin records that module's exact SHA-256. The original game's
version and source-file hashes were not recorded by the old generator, so this
seed explicitly leaves that provenance unknown. The separately maintained labels
in `gametool/fields.py` retain their higher runtime priority.

`editor-3.0.1.24371.json` contains every metadata record from the source's pinned
editor reference: 962 ability, 247 unit and 48 item records. It preserves every
raw metadata property, including both language labels, applicability, bounds,
table/field/index roles and extensions. Unresolved `WESTRING_*` Chinese labels
fall back to the complete English label; the unresolved original key remains in
this JSON. Source object profiles and stock object values are deliberately not
generator inputs.

The reference was obtained from the literal `_DATA` in
`war3_map_catalog_reference.py`, SHA-256
`ddb5b5fd4324754d3e9b7d409f1b30dc3920f0ccfb63c1b7bb2cec8b48d12988`.
Preparation parses Python's AST, accepts one literal string, decodes Base85 and
zlib, then parses JSON with duplicate-key rejection. It never imports or executes
that module. The JSON retains the source module hash, compressed literal hash,
decoded payload hash, canonical metadata hash, exact category counts and all 76
upstream source-file hashes. The latter are declarations embedded in the source
reference; this generator does not claim to have re-read those original game
installation files.

Run from a checkout with the locked development dependencies installed:

```powershell
uv run --offline --no-sync python -X utf8 build_field_labels.py
```

This default mode starts from the fixed seed and fills missing entries from the
complete reference. It adds 230 readable labels and 198 field types; 198 codes
previously had neither a label nor a type. It also adds 188 applicability and 188
bound entries. All existing seed entries, including all 727 common.j constants,
are preserved. Each addition has a version/category/language provenance entry;
every differing reference value is retained in
`GENERATED_FIELD_SOURCE_DIFFERENCES`. A preserved seed constraint is not evidence
that the new version has the same constraint.

`GENERATED_FIELD_SOURCE_MANIFEST` identifies every input by full SHA-256.
`GENERATED_FIELD_PROVENANCE` identifies additions or explicitly rebuilt entries;
entries absent from this mapping originate in the seed. The two JSON inputs and
generated Python have LF Git attributes, so Windows checkout conversion does not
change their hashes. The locked development Ruff formatter produces canonical
Python without network access. The generator does not depend on a target path,
working directory, previously generated output, game installation or source repo.

Prepare a future source reference without running its code:

```powershell
uv run --offline --no-sync python -X utf8 build_field_labels.py --import-reference-source C:\reference\war3_map_catalog_reference.py --reference-out data\field_metadata\editor-VERSION.json
uv run --offline --no-sync python -X utf8 build_field_labels.py --reference data\field_metadata\editor-VERSION.json --out C:\review\field_meta.py
```

Review the complete metadata and retained differences before changing the default
reference. An alternative `--seed` explicitly selects a different preserved
project baseline; do not silently re-label an old seed as a current game version.

Full original metadata remains supported:

```powershell
uv run --offline --no-sync python -X utf8 build_field_labels.py --meta-dir C:\metadata --source-version VERSION --common-j C:\metadata\common.j --out C:\review\field_meta.py
```

This explicit mode requires all eight configured metadata SLKs, each with real
rows and unique required columns. Malformed, truncated, empty or conflicting
inputs stop generation. Once all inputs pass, applicability and bounds are
rebuilt from those complete SLKs; label/type vocabulary from the seed and pinned
reference remains preserved, with source differences recorded. Supplying a valid
`--common-j` replaces the entire constant table. Omitting it preserves the seed
constants. An empty or ambiguous common.j fails instead of erasing the table.

Validation and formatting finish before `safe_output.write_text_safely` stages
and publishes the complete module. Failures before publication leave previous
output bytes unchanged. The shared safe writer owns atomic replacement and
recovery retention; post-publication storage/concurrency failures follow that
writer's evidence-preserving recovery contract. There is no direct-write fallback.
