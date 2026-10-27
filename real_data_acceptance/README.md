# Explicit original-input acceptance

These five tests retain their complete original bodies and assertions: one real Windows CASC installation test and four historical original-map/old-output/new-output comparisons. The three in-memory TSV helper regressions stay in the Windows product tests.

They are not part of default Windows regression. Select `uv run gamexray-test --suite real-data --lane casc --war3-dir <root>` or `--lane historical --maps-root <root> --old-output <root> --new-output <root>` explicitly. `--lane all` requests all five. The corresponding named GAMEXRAY environment variables are accepted only after explicit real-data scope selection.

Missing directories return 2 before tests launch, not skip or pass. A Classic MPQ installation cannot substitute for the required CASC installation. Once selected, any assertion/collection failure or skip/xfail/xpass is a hard failure. Paths are read-only inputs; runtime caches and reports use private temporary roots. Do not change historical counts, replace the original cohort, or infer that an unrequested lane was verified.
