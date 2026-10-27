# Retired native backend contracts

This is an independent source-evidence library, outside the Windows product regression testpaths. It contains 302 original parameter cases (218 complete original functions) for native adapters, plus four preserved full-publication integration parameter cases beside their Windows semantic counterparts. No assertion or original native function AST was changed by the physical move.

The reviewed mapping and function hashes are in ../scope-manifest.json. That manifest also names mandatory Windows contracts; moving a native adapter does not waive the Windows no-follow, publication, cache, source-proof, or cleanup contract. The two zero-side-effect capability preflight guards remain active Windows tests. Shared codec/schema/comparison tests remain under tests/ with portable fixtures.

Use `uv run gamexray-test --suite retired-posix` only in a runtime that provides the real native primitives. Windows refuses that explicit scope before pytest. Running this evidence library is not a macOS/Linux product support claim. Every result remains real; any skip/xfail/xpass or failure makes the explicit scope fail.
