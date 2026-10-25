r"""AST-level scan for SyntaxWarning-prone string literals (invalid escapes).

Heredoc workflows can silently downgrade `\n` to a real newline or `\/` to an
invalid escape inside checked-in sources; ruff/basedpyright do not flag them.
This gate compiles every file with SyntaxWarning promoted to an error so the
next regression fails loudly here instead of at import time on user machines.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path


def scan(paths: list[str]) -> int:
    failures: list[tuple[str, str]] = []
    for raw in paths:
        path = Path(raw)
        targets = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for py in targets:
            if not py.is_file():
                continue
            source = py.read_bytes()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", SyntaxWarning)
                    compile(source, str(py), "exec")
            except SyntaxWarning as exc:
                failures.append((str(py), str(exc)))
            except SyntaxError as exc:  # genuine syntax errors also fail the gate
                failures.append((str(py), f"SyntaxError: {exc}"))
    if failures:
        print(f"syntax-warnings: {len(failures)} file(s) failed", file=sys.stderr)
        for name, message in failures:
            print(f"  {name}: {message}", file=sys.stderr)
        return 1
    print("syntax-warnings: all clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(scan(sys.argv[1:]))
