"""
Task 4 — layering lint.

canonical/, context/, agents/, and api/ may not import the adapter
layer (scout.gmail, scout.connectors) or vendor SDKs used only by
adapters (googleapiclient). This is an architectural boundary, checked
statically via ast so it holds even for modules nobody has imported
yet.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CHECKED_DIRS = [
    "scout/canonical",
    "scout/context",
    "scout/agents",
    "scout/api",
]

FORBIDDEN_IMPORTS = [
    "scout.gmail",
    "scout.connectors",
    "googleapiclient",
]


def _imported_modules(tree: ast.Module) -> list[str]:
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _is_forbidden(module: str) -> str | None:
    for forbidden in FORBIDDEN_IMPORTS:
        if module == forbidden or module.startswith(forbidden + "."):
            return forbidden
    return None


def _iter_python_files():
    for rel_dir in CHECKED_DIRS:
        directory = REPO_ROOT / rel_dir
        if not directory.exists():
            continue
        yield from directory.rglob("*.py")


def test_no_forbidden_imports_in_layered_directories():
    violations = []

    for path in _iter_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for module in _imported_modules(tree):
            forbidden = _is_forbidden(module)
            if forbidden is None:
                continue

            rel_path = path.relative_to(REPO_ROOT).as_posix()
            violations.append(
                f"{rel_path} imports {module} — canonical/ may not import "
                f"adapters (Task 4)"
            )

    assert not violations, "Layering violations found:\n" + "\n".join(violations)
