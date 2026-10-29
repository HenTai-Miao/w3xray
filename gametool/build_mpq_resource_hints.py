"""Generate pinned, inert MPQ hints without importing or evaluating source code.

Run ``python -m gametool.build_mpq_resource_hints --source-root <checkout>``.
Only the literal in ``STANDARD_RESOURCE_NAMES`` and the pinned provenance
document are read. Neither a game installation nor this source checkout is
needed when the generated catalog is used by archive recovery.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
from collections.abc import Sequence
from typing import Final

from .safe_output import SafeWriteStatus, write_text_safely

CATALOG_ID: Final = "trainer-mpq-resource-hints-v1"
SOURCE_REPOSITORY: Final = "war3-reforged-trainer"
SOURCE_COMMIT: Final = "39ddabe2dc16ca7c3be9911c41dc22c83d1b9c4d"
SOURCE_FILE: Final = "war3_mpq_names.py"
SOURCE_FILE_SHA256: Final = (
    "adeaf732c55c11929dc8e5e59d69f4a699e89f80e529faf3a7e27a1357ab1ac9"
)
SOURCE_DOCUMENT: Final = "docs/MPQ_MEMBER_RECOVERY.md"
SOURCE_DOCUMENT_SHA256: Final = (
    "b323153c565e9af139552dfe74d8483b3323298687683c22b9c51184b1a968ec"
)


def _method_receiver(node: ast.expr, method: str) -> ast.expr:
    if (
        not isinstance(node, ast.Call)
        or node.args
        or node.keywords
        or not isinstance(node.func, ast.Attribute)
        or node.func.attr != method
    ):
        raise ValueError(f"resource hints require literal .{method}()")
    return node.func.value


def extract_resource_names(source: bytes) -> tuple[str, ...]:
    """Accept the documented literal shape; never execute an AST expression."""
    module = ast.parse(source.decode("utf-8-sig"), filename=SOURCE_FILE)
    statements = list(module.body)
    if statements and isinstance(statements[0], ast.Expr):
        docstring = statements[0].value
        if isinstance(docstring, ast.Constant) and isinstance(docstring.value, str):
            statements.pop(0)
    if len(statements) != 1 or not isinstance(statements[0], ast.Assign):
        raise ValueError("resource hints require exactly one literal assignment")
    assignment = statements[0]
    if (
        len(assignment.targets) != 1
        or not isinstance(assignment.targets[0], ast.Name)
        or assignment.targets[0].id != "STANDARD_RESOURCE_NAMES"
    ):
        raise ValueError("resource hints require STANDARD_RESOURCE_NAMES")
    value = assignment.value
    if (
        not isinstance(value, ast.Call)
        or not isinstance(value.func, ast.Name)
        or value.func.id != "tuple"
        or len(value.args) != 1
        or value.keywords
    ):
        raise ValueError("resource hints require tuple(literal.strip().splitlines())")
    literal = _method_receiver(_method_receiver(value.args[0], "splitlines"), "strip")
    if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
        raise ValueError("resource hints require a string literal")
    names = tuple(literal.value.strip().splitlines())
    if not names:
        raise ValueError("resource hints cannot be empty")
    for name in names:
        path = PureWindowsPath(name)
        if (
            not name
            or name != name.strip()
            or path.anchor
            or any(part in {"", ".", ".."} for part in name.split("\\"))
            or any(ord(char) < 32 or char in '/:*?"<>|' for char in name)
        ):
            raise ValueError(f"unsafe resource hint: {name!r}")
    # Preserve original spelling, order and repeated encoded lines. MPQ lookup
    # and safe output own their respective identity and filesystem boundaries.
    return names


def extract_document_provenance(
    document: bytes,
) -> tuple[int, tuple[tuple[str, str], ...]]:
    """Keep the source's declared count and every hashed upstream input row."""
    text = document.decode("utf-8-sig")
    counts = re.findall(r"`war3_mpq_names\.py` 内含 ([0-9]+) 条固定路径", text)
    if len(counts) != 1:
        raise ValueError("resource provenance requires one declared path count")
    references = tuple(
        (name.strip().strip("`"), digest.lower())
        for name, digest in re.findall(
            r"^\|\s*(.*?)\s*\|\s*`([a-fA-F0-9]{64})`\s*\|\s*$",
            text,
            re.MULTILINE,
        )
    )
    if not references or len({name for name, _ in references}) != len(references):
        raise ValueError("resource provenance requires distinct upstream inputs")
    return int(counts[0]), references


def render_catalog(source: bytes, document: bytes) -> str:
    """Validate pinned input bytes completely before generating any output."""
    for label, data, expected in (
        (SOURCE_FILE, source, SOURCE_FILE_SHA256),
        (SOURCE_DOCUMENT, document, SOURCE_DOCUMENT_SHA256),
    ):
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"pinned resource input SHA256 mismatch: {label}")
    names = extract_resource_names(source)
    declared_count, references = extract_document_provenance(document)
    if len(names) != declared_count:
        raise ValueError(
            f"resource hint count mismatch: declared={declared_count}, actual={len(names)}"
        )
    names_digest = hashlib.sha256(("\n".join(names) + "\n").encode("utf-8")).hexdigest()
    lines = [
        '"""Generated MPQ name hints; hashes and entry reads must confirm each name.',
        "",
        "Regenerate with gametool.build_mpq_resource_hints. These source-declared",
        "resource names do not certify a game version, installed assets or presence",
        "in any archive. Source code is parsed as literals and is never executed.",
        '"""',
        "",
        "from typing import Final",
        "",
        "CATALOG_SCHEMA_VERSION: Final = 1",
    ]
    for key, value in (
        ("CATALOG_ID", CATALOG_ID),
        ("SOURCE_REPOSITORY", SOURCE_REPOSITORY),
        ("SOURCE_COMMIT", SOURCE_COMMIT),
        ("SOURCE_FILE", SOURCE_FILE),
        ("SOURCE_FILE_SHA256", SOURCE_FILE_SHA256),
        ("SOURCE_DOCUMENT", SOURCE_DOCUMENT),
        ("SOURCE_DOCUMENT_SHA256", SOURCE_DOCUMENT_SHA256),
        ("RESOURCE_NAMES_SHA256", names_digest),
    ):
        value_line = f"{key}: Final = {json.dumps(value, ensure_ascii=False)}"
        if len(value_line) <= 88:
            lines.append(value_line)
        else:
            lines.extend((f"{key}: Final = (", f"    {json.dumps(value)}", ")"))
    lines.extend((f"RESOURCE_NAME_COUNT: Final = {len(names)}", ""))
    lines.append("SOURCE_REFERENCE_SHA256: Final = (")
    for name, digest in references:
        lines.extend(
            (
                "    (",
                f"        {json.dumps(name, ensure_ascii=False)},",
                f"        {json.dumps(digest)},",
                "    ),",
            )
        )
    lines.extend((")", "", "RESOURCE_NAME_HINTS: Final = ("))
    lines.extend(f"    {json.dumps(name, ensure_ascii=False)}," for name in names)
    lines.extend((")", ""))
    return "\n".join(lines)


def generate_catalog(source_root: Path, output: Path) -> None:
    """Publish only after complete validation, keeping source inputs read-only."""
    source_root = source_root.resolve(strict=True)
    output = output.absolute()
    if output.resolve().is_relative_to(source_root):
        raise ValueError("resource catalog output must be outside the source checkout")
    source_path = source_root / SOURCE_FILE
    document_path = source_root / SOURCE_DOCUMENT
    source = source_path.read_bytes()
    document = document_path.read_bytes()
    rendered = render_catalog(source, document)
    if source_path.read_bytes() != source or document_path.read_bytes() != document:
        raise ValueError("resource catalog inputs changed before publication")
    result = write_text_safely(str(output.parent), output.name, rendered)
    if result.status is not SafeWriteStatus.WRITTEN:
        raise OSError(f"resource catalog publication failed: {result.status.name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("mpq_resource_hints.py")
    )
    args = parser.parse_args(argv)
    generate_catalog(args.source_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
