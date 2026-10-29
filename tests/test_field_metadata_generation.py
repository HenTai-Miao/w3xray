"""Full offline metadata, source identity and no-partial-publication contracts."""

from __future__ import annotations

import ast
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import zlib

import pytest

import build_field_labels as bfl
from gametool import field_meta, safe_output
from gametool.dev_test import create_test_environment
from gametool.field_metadata_generation import (
    MetadataInputError,
    TABLE_NAMES,
    canonical_json,
    load_seed,
    read_reference,
    reference_from_source,
    sha256,
)
from gametool.fields import FIELD_LABELS, field_type, label_for as field_label


def _slk(code: str, *, label: str = "Fixture", typ: str = "string") -> str:
    return (
        'ID;PWXL\nB;Y2;X3\nC;X1;Y1;K"id"\n'
        'C;X2;Y1;K"displayName"\nC;X3;Y1;K"type"\n'
        f'C;X1;Y2;K"{code}"\nC;X2;Y2;K"{label}"\n'
        f'C;X3;Y2;K"{typ}"\nE\n'
    )


def _complete_meta(tmp_path: Path) -> Path:
    root = tmp_path / "metadata"
    for index, relative in enumerate(bfl._META_FILES):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_slk(f"z{index:03}"), encoding="latin-1")
    return root


def _target(tmp_path: Path) -> tuple[Path, bytes]:
    path = tmp_path / "existing.py"
    previous = b"# exact previous output\r\nOLD = {'preserve': 123}\r\n"
    path.write_bytes(previous)
    return path, previous


def _tables(path: Path):
    return {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }


def test_complete_reference_fills_all_missing_fields_with_versioned_provenance():
    reference, raw = read_reference(bfl.DEFAULT_REFERENCE)
    seed = load_seed(bfl.DEFAULT_SEED)
    result = bfl.build_generation()
    assert reference["record_counts"] == {"ability": 962, "unit": 247, "item": 48}
    assert result.found == 1257
    expected_missing = {"ability": 185, "unit": 8, "item": 5}
    for category, rows in reference["metadata"].items():
        missing = {
            code
            for code in rows
            if code not in seed.tables["FIELD_TYPES"]
            and code not in seed.tables["GENERATED_FIELD_LABELS"]
            and code not in FIELD_LABELS
        }
        assert len(missing) == expected_missing[category]
        for code in rows:
            assert result.tables["GENERATED_FIELD_LABELS"][code]
            assert result.tables["FIELD_TYPES"][code]
        for code in missing:
            assert field_label(code) != code
            assert field_type(code) == rows[code]["type"]
            for table in ("GENERATED_FIELD_LABELS", "FIELD_TYPES"):
                assert result.provenance[code][table].startswith(
                    f"editor-reference:3.0.1.24371:{category}"
                )
    assert result.sources["editor-reference:3.0.1.24371"]["sha256"] == sha256(raw)
    assert len(result.sources["editor-reference:3.0.1.24371"]["source_hashes"]) == 76
    for table in TABLE_NAMES:
        assert all(
            result.tables[table][code] == value
            for code, value in seed.tables[table].items()
        )
        assert result.tables[table] == getattr(field_meta, table)
    assert result.retained_differences  # Version disagreements are not silently erased.


@pytest.mark.parametrize(
    ("code", "label", "typ"),
    [
        ("iequ", "Equipment Type", "equipmentType"),
        ("itag", "标签", "itemTag"),
        ("itco", "队伍颜色", "teamColor"),
        ("iinv", "无敌", "bool"),
        ("upor", "头像模型文件", "model"),
        ("Icr1", "Cooldown Reduction", "unreal"),
    ],
)
def test_new_field_metadata_is_available_to_existing_runtime_helpers(code, label, typ):
    assert field_label(code) == label
    assert field_type(code) == typ


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "header_only",
        "truncated",
        "conflicting_cell",
        "duplicate_header",
        "missing_type",
        "cross_file_conflict",
    ],
)
def test_invalid_slk_inputs_preserve_existing_output(tmp_path, damage, capsys):
    root = _complete_meta(tmp_path)
    path = root / bfl._META_FILES[-1]
    if damage == "missing":
        path.unlink()
    elif damage == "empty":
        path.write_text("", encoding="latin-1")
    elif damage == "header_only":
        path.write_text(
            'ID;PWXL\nC;X1;Y1;K"id"\nC;X2;Y1;K"displayName"\nC;X3;Y1;K"type"\nE\n',
            encoding="latin-1",
        )
    elif damage == "truncated":
        path.write_text(_slk("z007").removesuffix("E\n"), encoding="latin-1")
    elif damage == "conflicting_cell":
        path.write_text(
            _slk("z007").replace("E\n", 'C;X3;Y2;K"int"\nE\n'), encoding="latin-1"
        )
    elif damage == "duplicate_header":
        path.write_text(
            _slk("z007").replace("E\n", 'C;X4;Y1;K"type"\nC;X4;Y2;K"string"\nE\n'),
            encoding="latin-1",
        )
    elif damage == "missing_type":
        path.write_text(_slk("z007", typ=""), encoding="latin-1")
    else:
        path.write_text(
            _slk("z000", label="Conflicting definition"), encoding="latin-1"
        )
    target, previous = _target(tmp_path)
    assert bfl.main(["--meta-dir", str(root), "--out", str(target)]) == 2
    assert target.read_bytes() == previous
    assert "failed" in capsys.readouterr().err


def test_explicit_complete_slks_replace_bounds_applicability_and_optional_constants(
    tmp_path,
):
    root = _complete_meta(tmp_path)
    path = root / bfl._META_FILES[1]
    path.write_text(
        _slk("Efk1", typ="unreal").replace(
            "E\n",
            'C;X4;Y1;K"useSpecific"\nC;X4;Y2;K"Anew"\nC;X5;Y1;K"minVal"\nC;X5;Y2;K"-7"\nE\n',
        ),
        encoding="latin-1",
    )
    result = bfl.build_generation(str(root), source_version="test-build")
    assert result.tables["GENERATED_FIELD_APPLICABILITY"] == {"Efk1": (("Anew",), ())}
    assert result.tables["GENERATED_FIELD_BOUNDS"] == {"Efk1": ("-7", None)}
    assert (
        result.tables["GENERATED_FIELD_CONSTANTS"]
        == field_meta.GENERATED_FIELD_CONSTANTS
    )
    for rel in bfl._META_FILES:
        assert result.sources[f"metadata-slk:{rel}"]["sha256"] == sha256(
            (root / rel).read_bytes()
        )
    common = tmp_path / "common.j"
    common.write_text(
        "constant abilityreallevelfield TEST_NEW = ConvertAbilityRealLevelField('z999')\n",
        encoding="utf-8",
    )
    explicit = bfl.build_generation(str(root), str(common))
    assert explicit.tables["GENERATED_FIELD_CONSTANTS"] == {"z999": "TEST_NEW"}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "// constant abilityrealfield FAKE = ConvertAbilityRealField('abcd')\n",
        "constant abilityrealfield BAD = 1\n",
        "constant abilityrealfield ONE = ConvertAbilityRealField('abcd')\nconstant abilityrealfield TWO = ConvertAbilityRealField('abcd')\n",
        "constant abilityrealfield ONE = ConvertAbilityRealField('abcd') + 1\n",
    ],
)
def test_invalid_explicit_constants_preserve_output(tmp_path, text):
    common = tmp_path / "common.j"
    common.write_text(text, encoding="utf-8")
    target, previous = _target(tmp_path)
    assert bfl.main(["--common-j", str(common), "--out", str(target)]) == 2
    assert target.read_bytes() == previous


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "category",
        "counts",
        "hash",
        "duplicate_key",
        "schema",
        "conflicting_category",
    ],
)
def test_invalid_reference_does_not_publish(tmp_path, damage):
    reference = tmp_path / "reference.json"
    data = json.loads(bfl.DEFAULT_REFERENCE.read_text(encoding="utf-8"))
    if damage == "category":
        del data["metadata"]["unit"]
    elif damage == "counts":
        data["record_counts"]["ability"] -= 1
    elif damage == "hash":
        data["metadata"]["item"]["iequ"]["type"] = "changed"
    elif damage == "schema":
        data["schema"] = 2
    elif damage == "conflicting_category":
        data["metadata"]["unit"]["iequ"] = {"type": "int", "enUS": "Different"}
        data["record_counts"]["unit"] += 1
        data["metadata_sha256"] = sha256(
            canonical_json(data["metadata"]).encode("utf-8")
        )
    text = canonical_json(data)
    if damage == "duplicate_key":
        text = text.replace('"schema": 1,', '"schema": 1, "schema": 1,', 1)
    if damage != "missing":
        reference.write_text("" if damage == "empty" else text, encoding="utf-8")
    target, previous = _target(tmp_path)
    assert bfl.main(["--reference", str(reference), "--out", str(target)]) == 2
    assert target.read_bytes() == previous


def test_formatter_failure_preserves_previous_bytes(tmp_path, monkeypatch):
    target, previous = _target(tmp_path)

    def fail(_text):
        raise subprocess.CalledProcessError(2, ["formatter"])

    monkeypatch.setattr(bfl, "_format_module", fail)
    assert bfl.main(["--out", str(target)]) == 2
    assert target.read_bytes() == previous


@pytest.mark.parametrize(
    "damage", ["missing", "empty", "tables_type", "incomplete", "hash"]
)
def test_invalid_seed_does_not_publish(tmp_path, damage):
    seed = tmp_path / "seed.json"
    data = json.loads(bfl.DEFAULT_SEED.read_text(encoding="utf-8"))
    if damage == "tables_type":
        data["tables"] = 7
    elif damage == "incomplete":
        del data["tables"]["FIELD_TYPES"]
    elif damage == "hash":
        data["tables"]["FIELD_TYPES"]["Efk1"] = "changed"
    if damage != "missing":
        seed.write_text(
            "" if damage == "empty" else canonical_json(data), encoding="utf-8"
        )
    target, previous = _target(tmp_path)
    assert bfl.main(["--seed", str(seed), "--out", str(target)]) == 2
    assert target.read_bytes() == previous


def test_hashed_inputs_and_generated_file_have_canonical_checkout_line_endings():
    root = Path(bfl.__file__).parent
    attributes = (root / ".gitattributes").read_text(encoding="utf-8")
    assert "data/field_metadata/*.json text eol=lf" in attributes.splitlines()
    assert "gametool/field_meta.py text eol=lf" in attributes.splitlines()
    for path in (bfl.DEFAULT_SEED, bfl.DEFAULT_REFERENCE, Path(field_meta.__file__)):
        assert b"\r" not in path.read_bytes(), path


def test_partial_stage_write_failure_preserves_previous_bytes(tmp_path, monkeypatch):
    target, previous = _target(tmp_path)

    def fail(descriptor, _chunks):
        os.write(descriptor, b"partial new module")
        raise OSError("injected stage failure")

    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)
    monkeypatch.setattr(safe_output, "write_chunks_to_descriptor", fail)
    assert bfl.main(["--out", str(target)]) == 2
    assert target.read_bytes() == previous
    assert sorted(path.name for path in tmp_path.iterdir()) == [target.name]


def test_publication_failure_preserves_previous_bytes(tmp_path, monkeypatch):
    target, previous = _target(tmp_path)

    def fail(*_args, **_kwargs):
        assert target.read_bytes() == previous
        raise OSError("injected publication failure")

    monkeypatch.setattr(safe_output, "_ANCHORED_WRITES_AVAILABLE", False)
    monkeypatch.setattr(safe_output, "publish_staged_path", fail)
    assert bfl.main(["--out", str(target)]) == 2
    assert target.read_bytes() == previous


def test_offline_generation_is_byte_reproducible_outside_checkout(tmp_path):
    outputs = [tmp_path / "first.py", tmp_path / "second.py"]
    for target in outputs:
        completed = subprocess.run(
            [sys.executable, str(Path(bfl.__file__).resolve()), "--out", str(target)],
            cwd=tmp_path,
            env=create_test_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert outputs[0].read_bytes() == Path(field_meta.__file__).read_bytes()
    assert (
        _tables(outputs[0])["GENERATED_FIELD_SOURCE_MANIFEST"]
        == field_meta.GENERATED_FIELD_SOURCE_MANIFEST
    )


def test_static_reference_import_never_executes_source(tmp_path):
    marker = tmp_path / "executed.txt"
    metadata = {
        category: {f"x{i:03}": {"enUS": "Name", "type": "string"}}
        for i, category in enumerate(("ability", "unit", "item"))
    }
    payload = {
        "schema": 1,
        "game_build": "3.0.1.24371",
        "metadata": metadata,
        "sources": {"metadata.slk": "a" * 64},
        "profiles": {"frozen_stock_value": 999},
    }
    decoded = canonical_json(payload).encode("utf-8")
    compressed = zlib.compress(decoded)
    encoded = base64.b85encode(compressed).decode("ascii")
    source = tmp_path / "reference_source.py"
    source.write_text(
        f"_DATA = {encoded!r}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('must never execute')\n",
        encoding="utf-8",
    )
    result = reference_from_source(source)
    assert not marker.exists()
    assert result["metadata"] == metadata
    assert "profiles" not in result
    assert result["origin"]["module_sha256"] == sha256(source.read_bytes())
    assert result["origin"]["decoded_payload_sha256"] == sha256(decoded)
    assert result["origin"]["compressed_literal_sha256"] == sha256(compressed)


@pytest.mark.parametrize(
    "source",
    ["_DATA = str('not a literal')", "_DATA = ''", "_DATA = 'abc'\n_DATA = 'xyz'"],
)
def test_static_reference_import_rejects_nonliteral_or_ambiguous_data(tmp_path, source):
    path = tmp_path / "reference_source.py"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(MetadataInputError):
        reference_from_source(path)
