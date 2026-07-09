# Task 1 Report: Real TriggerData and TriggerStrings Schema

## Scope

Implemented Task 1 in `/Users/zhongerbing/Documents/xm/war3_xg/w3xray` without
reverting unrelated work. Untracked `.DS_Store` files were left untouched.

## RED

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_trigger_schema.py -q -p no:cacheprovider
```

Key output:

```text
E   ModuleNotFoundError: No module named 'w3xtool.trigger_schema'
1 error in 0.04s
```

This was the expected failure and confirmed the new schema tests were exercising
the missing production module rather than a broken assertion.

## GREEN

Focused command:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest tests/test_trigger_schema.py tests/test_triggerdata_semantics.py -q -p no:cacheprovider
```

Key output:

```text
......                                                                   [100%]
6 passed in 0.17s
```

Full-suite command:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m pytest -q -p no:cacheprovider
```

Key output:

```text
539 passed, 15 skipped in 3.60s
```

## What Changed

- Added typed real-format schema parser in `w3xtool/trigger_schema.py`.
- Added duplicate-key TriggerStrings parser in `w3xtool/trigger_strings.py`.
- Reworked `w3xtool/triggerdata.py` to:
  - load both TriggerData and TriggerStrings from a source
  - render semantics from real templates
  - resolve `TRIGSTR_n` values during rendering
  - preserve a legacy template-shaped compatibility path for old callers
- Vendored attributed fixtures:
  - `tests/fixtures/trigger/TriggerData.txt`
  - `tests/fixtures/trigger/TriggerStrings.txt`
  - `tests/fixtures/trigger/README.md`
  - `tests/fixtures/licenses/War3Lib-Apache-2.0.txt`
- Added `tests/test_trigger_schema.py`.
- Rewrote `tests/test_triggerdata_semantics.py` to assert real TriggerData and
  TriggerStrings behavior instead of fake template semantics.

## Changed Files

- `w3xtool/trigger_schema.py`
- `w3xtool/trigger_strings.py`
- `w3xtool/triggerdata.py`
- `tests/fixtures/trigger/TriggerData.txt`
- `tests/fixtures/trigger/TriggerStrings.txt`
- `tests/fixtures/trigger/README.md`
- `tests/fixtures/licenses/War3Lib-Apache-2.0.txt`
- `tests/test_trigger_schema.py`
- `tests/test_triggerdata_semantics.py`
- `.superpowers/sdd/task-1-report.md`

## Self-Review

- The real parser never treats TriggerData signatures as display text.
- TriggerStrings duplicate keys are preserved in order and used to derive the
  localized display name plus positional semantic template.
- `load_trigger_schema_from_source()` reads both files and returns `None` on the
  brief-specified source failures, including `CascUnsupportedError`.
- Semantic rendering no longer emits raw signature text such as
  `0,force,StringExt(...)`.
- Each new or extended Python module stays below the 250 pure-LOC ceiling:
  - `w3xtool/trigger_schema.py`: 96
  - `w3xtool/trigger_strings.py`: 59
  - `w3xtool/triggerdata.py`: 207

## Notes / Residual Concern

- The cross-kind schema lookup fallback in semantic rendering is an intentional
  compatibility guard for nested WTG functions whose runtime `function_type`
  does not align with the TriggerData section that defines the same function
  name. Tests cover the observed case.
