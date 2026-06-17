"""
Checker engine — DEPRECATED for production use.

In production, the checker runs INSIDE the Docker sandbox via docker/run.py,
eliminating the host-side exec() security vulnerability.

This module is kept as a utility for:
  - Local development / unit tests without Docker
  - Admin-side syntax validation before saving checker code
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_checker_syntax(checker_code: str) -> Optional[str]:
    """
    Compile-check that checker_code defines a valid `check` function.

    Returns None on success, or an error string on failure.
    Only call this at admin problem-save time, never during judging.
    """
    if not checker_code or not checker_code.strip():
        return None  # Empty = use default checker

    try:
        code_obj = compile(checker_code, "<checker>", "exec")
        namespace: dict = {}
        exec(code_obj, namespace)  # noqa: S102 — admin-only, not user code
        if not callable(namespace.get("check")):
            return "Checker must define a callable 'check(test_input, user_output, expected_output)' function."
        return None
    except SyntaxError as exc:
        return f"Syntax error in checker: {exc}"
    except Exception as exc:
        return f"Error loading checker: {exc}"
