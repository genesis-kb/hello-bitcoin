"""
Checker syntax validator — checks that checker code is syntactically valid
and defines a callable `check` function, WITHOUT executing the code.

In production, the checker runs INSIDE the Docker sandbox via docker/run.py,
eliminating the host-side exec() security vulnerability.

This module is kept as a utility for:
  - Local development / unit tests without Docker
  - Admin-side syntax validation before saving checker code
"""

import ast
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_checker_syntax(checker_code: str) -> Optional[str]:
    """
    Compile-check that checker_code defines a valid `check` function.

    Returns None on success, or an error string on failure.
    Only call this at admin problem-save time, never during judging.

    Security: this function deliberately does NOT exec() the code.
    Admin-provided checker code is executed only inside the Docker sandbox.
    """
    if not checker_code or not checker_code.strip():
        return None  # Empty = use default checker

    try:
        tree = ast.parse(checker_code, filename="<checker>")
    except SyntaxError as exc:
        return f"Syntax error in checker: {exc}"
    except Exception as exc:
        return f"Parse error in checker: {exc}"

    # Verify that a top-level function named 'check' is defined
    has_check = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "check"
        for node in ast.walk(tree)
    )
    if not has_check:
        return "Checker must define a callable 'check(test_input, user_output, expected_output)' function."

    return None
