"""Reproducibly generate field_meta.py from complete, offline metadata inputs.

The default uses the checked-in seed and complete versioned editor reference.
The reference fills gaps in all tables and retains every version difference;
it never supplies current-game object values. Explicit --meta-dir requires all
eight SLKs before rebuilding applicability/bounds. Labels/types retain existing
values. Explicit --common-j replaces constants; omission preserves them.

Static source preparation (the source module is never imported or executed):
    python build_field_labels.py --import-reference-source <reference.py> \
        --reference-out data/field_metadata/editor-<version>.json
Offline generation:
    uv run --offline --no-sync python build_field_labels.py
Full SLK refresh:
    python build_field_labels.py --meta-dir <root> --source-version <version> \
        [--common-j <common.j>]
All parsing and pinned-development-Ruff formatting finish before safe publication.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from pprint import pformat
import re
import subprocess
import sys

from gametool import westrings as _west_module
from gametool.field_metadata_generation import (
    Generation,
    MetadataInputError,
    TABLE_NAMES,
    canonical_json,
    load_seed,
    merge_reference,
    publish_text,
    reference_from_source,
    sha256,
    split_codes,
)
from gametool.script_lexing import script_views
from gametool.slk_evidence import parse_slk_evidence

_ROOT = Path(__file__).resolve().parent
_DATA = _ROOT / "data" / "field_metadata"
DEFAULT_SEED = _DATA / "legacy-0.9.0.json"
DEFAULT_REFERENCE = _DATA / "editor-3.0.1.24371.json"
_WESTRINGS: dict[str, str] = dict(_west_module.WESTRINGS)
_META_FILES = (
    "units/unitmetadata.slk",
    "units/abilitymetadata.slk",
    "units/upgrademetadata.slk",
    "units/miscmetadata.slk",
    "units/destructablemetadata.slk",
    "units/abilitybuffmetadata.slk",
    "units/upgradeeffectmetadata.slk",
    "doodads/DoodadMetaData.slk",
)
_CTRL = re.compile(r"[\x00-\x1f]+")
_ABILITY_FIELD_DECL = re.compile(r"\bconstant\s+ability\w*field\b")
_ABILITY_FIELD_CONST = re.compile(
    r"constant\s+ability\w*field\s+(\w+)\s*=\s*"
    r"ConvertAbility\w+\(\s*'([^'\r\n]{4})'\s*\)"
)


def resolve_westring(key: str) -> str:
    """Resolve complete WESTRING chains, retaining unknown keys and breaking cycles."""
    seen: set[str] = set()
    value = key
    while value.upper().startswith("WESTRING_") and value not in seen:
        seen.add(value)
        following = _WESTRINGS.get(value) or _WESTRINGS.get(value.upper())
        if following is None:
            break
        value = following
    return _CTRL.sub("", value)


def _split_codes(value: str) -> tuple[str, ...]:
    return split_codes(value)


def _constants_from_bytes(raw: bytes, origin: str) -> dict[str, str]:
    text = script_views(raw.decode("utf-8-sig"), lua=False).code
    constants: dict[str, str] = {}
    names: dict[str, str] = {}
    for declaration in _ABILITY_FIELD_DECL.finditer(text):
        match = _ABILITY_FIELD_CONST.match(text, declaration.start())
        if match is None:
            raise MetadataInputError(
                f"{origin}: unrecognized ability field declaration"
            )
        line_end = text.find("\n", match.end())
        remainder = text[match.end() : line_end if line_end >= 0 else len(text)]
        if remainder.strip():
            raise MetadataInputError(
                f"{origin}: extra syntax after ability field declaration"
            )
        name, code = match.groups()
        if (code in constants and constants[code] != name) or (
            name in names and names[name] != code
        ):
            raise MetadataInputError(
                f"{origin}: conflicting ability constant {name}/{code}"
            )
        constants[code], names[name] = name, code
    if not constants:
        raise MetadataInputError(f"{origin}: no ability field constants")
    return constants


def build_constants(common_j_path: str) -> dict[str, str]:
    path = Path(common_j_path)
    return _constants_from_bytes(path.read_bytes(), path.name)


def _read_complete_slks(meta_dir: Path):
    missing = [rel for rel in _META_FILES if not (meta_dir / rel).is_file()]
    if missing:
        raise MetadataInputError("missing required metadata: " + ", ".join(missing))
    captured = {rel: (meta_dir / rel).read_bytes() for rel in _META_FILES}
    parsed: dict[str, dict[str, dict[str, str]]] = {}
    seen: dict[str, tuple[dict[str, str], str]] = {}
    for rel, raw in captured.items():
        evidence = parse_slk_evidence(raw.decode("latin-1"), raw_bytes=raw)
        problems = [
            issue
            for issue in evidence.diagnostics
            if issue.conflict
            or issue.code not in {"duplicate_cell", "duplicate_object_id"}
        ]
        if problems:
            raise MetadataInputError(
                rel
                + ": "
                + "\n".join(evidence.diagnostic_text(issue) for issue in problems)
            )
        headers = {column.name for column in evidence.columns}
        if not {"displayName", "type"} <= headers:
            raise MetadataInputError(f"{rel}: missing displayName/type headers")
        rows = evidence.as_dict()
        if not rows:
            raise MetadataInputError(f"{rel}: metadata has no records")
        for code, row in rows.items():
            if not row.get("type"):
                raise MetadataInputError(f"{rel}: missing type for {code!r}")
            prior = seen.get(code)
            if prior is not None and prior[0] != row:
                raise MetadataInputError(
                    f"ambiguous metadata {code!r}: {prior[1]} and {rel}"
                )
            seen[code] = (row, rel)
        parsed[rel] = rows
    return parsed, captured


def build_generation(
    meta_dir: str | None = None,
    common_j_path: str | None = None,
    *,
    seed: Path = DEFAULT_SEED,
    reference: Path = DEFAULT_REFERENCE,
    source_version: str = "unspecified",
) -> Generation:
    result = load_seed(seed)
    merge_reference(result, reference)
    if meta_dir is not None:
        parsed, captured = _read_complete_slks(Path(meta_dir))
        result.found = result.unresolved = 0
        for table in ("GENERATED_FIELD_APPLICABILITY", "GENERATED_FIELD_BOUNDS"):
            result.tables[table] = {}
            for provenance in result.provenance.values():
                provenance.pop(table, None)
        for rel, rows in parsed.items():
            source = f"metadata-slk:{rel}"
            result.sources[source] = {
                "file": rel,
                "sha256": sha256(captured[rel]),
                "source_version": source_version,
                "records": len(rows),
            }
            for code, row in rows.items():
                result.found += 1
                label = resolve_westring(row.get("displayName", ""))
                result.fill("FIELD_TYPES", code, row["type"], source)
                if label and not label.upper().startswith("WESTRING_"):
                    result.fill("GENERATED_FIELD_LABELS", code, label, source)
                else:
                    result.unresolved += 1
                use, avoid = (
                    split_codes(row.get("useSpecific", "")),
                    split_codes(row.get("notSpecific", "")),
                )
                if use or avoid:
                    result.fill(
                        "GENERATED_FIELD_APPLICABILITY", code, (use, avoid), source
                    )
                lo, hi = row.get("minVal") or None, row.get("maxVal") or None
                if lo is not None or hi is not None:
                    result.fill("GENERATED_FIELD_BOUNDS", code, (lo, hi), source)
        result.sources["westrings"] = {
            "file": "gametool/westrings.py",
            "sha256": sha256((_ROOT / "gametool" / "westrings.py").read_bytes()),
        }
    if common_j_path is not None:
        path = Path(common_j_path)
        raw = path.read_bytes()
        constants = _constants_from_bytes(raw, path.name)
        result.tables["GENERATED_FIELD_CONSTANTS"] = constants
        result.sources["common-j"] = {
            "file": path.name,
            "sha256": sha256(raw),
            "source_version": source_version,
        }
        for code in constants:
            result.provenance.setdefault(code, {})["GENERATED_FIELD_CONSTANTS"] = (
                "common-j"
            )
    return result


def build(meta_dir: str, common_j_path: str | None = None):
    """Compatibility seven-tuple; complete explicit SLKs rebuild extra tables."""
    return build_generation(meta_dir, common_j_path).legacy_tuple()


def _format_module(text: str) -> str:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "format",
        "--isolated",
        "--line-length",
        "88",
        "--target-version",
        "py314",
        "--stdin-filename",
        "field_meta.py",
        "-",
    ]
    result = subprocess.run(
        command,
        input=text,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    ast.parse(result.stdout)
    return result.stdout


def render_module(
    labels,
    types,
    applicability,
    bounds,
    constants,
    *,
    generation: Generation | None = None,
):
    lines = [
        '"""对象字段标签 / 类型 / 适用性 / 值域 / 常量名，由 build_field_labels.py 离线生成。',
        "",
        "默认输入为已提交的历史 seed 与完整版本化编辑器元数据；新版本仅补缺。",
        "来源、版本差异见文件尾部；参考快照不代表当前游戏对象数值。",
        '运行时只查表。fields.py 的手工标签优先。请通过生成器更新。"""',
        "",
    ]
    for name, values in zip(
        TABLE_NAMES, (labels, types, applicability, bounds, constants), strict=True
    ):
        lines.extend(
            (
                f"{name} = {{",
                *(f"    {code!r}: {values[code]!r}," for code in sorted(values)),
                "}",
                "",
            )
        )
    if generation is not None:
        manifests = {
            "GENERATED_FIELD_CATEGORIES": generation.categories,
            "GENERATED_FIELD_CATEGORY_PROVENANCE": generation.category_provenance,
            "GENERATED_FIELD_SOURCE_MANIFEST": generation.sources,
            "GENERATED_FIELD_PROVENANCE": generation.provenance,
            "GENERATED_FIELD_SOURCE_DIFFERENCES": generation.retained_differences,
        }
        for name, values in manifests.items():
            lines.extend((f"{name} = {pformat(values, width=88, sort_dicts=True)}", ""))
    return _format_module("\n".join(lines))


def write_module(
    labels,
    types,
    applicability,
    bounds,
    constants,
    out_path,
    *,
    generation: Generation | None = None,
):
    text = render_module(
        labels, types, applicability, bounds, constants, generation=generation
    )
    publish_text(Path(out_path), text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--meta-dir", help="complete eight-SLK input; rebuild applicability/bounds"
    )
    parser.add_argument(
        "--common-j", help="replace constants from a validated common.j"
    )
    parser.add_argument("--source-version", default="unspecified")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument(
        "--out", type=Path, default=_ROOT / "gametool" / "field_meta.py"
    )
    parser.add_argument("--import-reference-source", type=Path)
    parser.add_argument("--reference-out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.import_reference_source is not None:
            if args.reference_out is None:
                raise MetadataInputError(
                    "--import-reference-source requires --reference-out"
                )
            reference = reference_from_source(args.import_reference_source)
            publish_text(args.reference_out, canonical_json(reference))
            print(
                f"Reference {reference['game_build']}: {reference['record_counts']}; {args.reference_out}"
            )
            return 0
        if args.reference_out is not None:
            raise MetadataInputError(
                "--reference-out requires --import-reference-source"
            )
        result = build_generation(
            args.meta_dir,
            args.common_j,
            seed=args.seed,
            reference=args.reference,
            source_version=args.source_version,
        )
        write_module(
            result.tables["GENERATED_FIELD_LABELS"],
            result.tables["FIELD_TYPES"],
            result.tables["GENERATED_FIELD_APPLICABILITY"],
            result.tables["GENERATED_FIELD_BOUNDS"],
            result.tables["GENERATED_FIELD_CONSTANTS"],
            args.out,
            generation=result,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Field metadata generation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Input records: {result.found}; unresolved labels: {result.unresolved}")
    print("; ".join(f"{name}={len(values)}" for name, values in result.tables.items()))
    print(f"Published {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
