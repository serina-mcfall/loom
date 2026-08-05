#!/usr/bin/env python3
"""Fail if anything in the project imports a package outside the standard library.

Loom's zero-dependency constraint is not a preference — it is the reason `loom`
can be dropped into any repo with a Python 3.10-or-newer interpreter and just run.
That constraint is invisible: nothing breaks the day someone adds `import requests`,
because the machine that added it already has requests installed. It breaks on
a fresh checkout, weeks later, for someone else.

(This docstring said "3.12" until 2026-08-05, which was a guess rather than a
measurement — see README for the versions actually tested. THIS SCRIPT is the reason
the floor is 3.10 rather than 3.9: `sys.stdlib_module_names` below only exists from
3.10. Loom's own runtime is fine on 3.9.)

So this checks it the only way that survives that: parse every import in the
tree and compare the top-level module name against `sys.stdlib_module_names`.

Whitelist, not blacklist. An import this script has never heard of is a
FAILURE, not a pass — the same rule the rest of the project follows, because a
blacklist's unknown case is "allowed" and that is how the constraint would rot.

Exit 0 = clean. Exit 1 = a non-stdlib import, or the tree could not be read.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# First-party packages: importable because they live here, not because they
# are installed. Kept explicit so a NEW top-level package must be added here
# deliberately rather than being silently accepted.
FIRST_PARTY = {"loom", "loom_cli", "hooks", "tests", "scripts"}

SKIP_DIRS = {".git", "__pycache__", ".superpowers", "node_modules", ".venv"}


def python_files(root: Path) -> list[Path]:
    out = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return sorted(out)


def imported_names(tree: ast.AST) -> set[str]:
    """Every top-level module name this file imports.

    `import a.b.c` and `from a.b import c` both attribute to `a` — the top
    level is what pip would have to install.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import — resolves inside this package,
            # never to an installed distribution.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    allowed = set(sys.stdlib_module_names) | FIRST_PARTY

    files = python_files(root)
    if not files:
        # An empty result would otherwise be indistinguishable from "clean" —
        # the exact empty-vs-broken confusion this project exists to refuse.
        print(f"FAIL: no Python files found under {root}", file=sys.stderr)
        return 1

    offences: list[tuple[Path, str]] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            print(f"FAIL: could not parse {path}: {exc}", file=sys.stderr)
            return 1
        for name in sorted(imported_names(tree)):
            if name not in allowed:
                offences.append((path.relative_to(root), name))

    if offences:
        print(f"FAIL: {len(offences)} non-stdlib import(s) found:", file=sys.stderr)
        for path, name in offences:
            print(f"  {path}: {name}", file=sys.stderr)
        print(
            "\nLoom is stdlib-only by design. If this import is genuinely needed, "
            "that is a design decision to make deliberately — not a check to "
            "silence.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(files)} Python files, every import is stdlib or first-party")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
