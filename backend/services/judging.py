"""
Judging service.

Decoupled from the route layer so it can be called from:
  - ARQ worker (process_submission task)
  - Direct background task (dev/test without Redis)
  - Unit tests

Key design decisions:
  - Test cases for a single submission are judged IN PARALLEL using asyncio.gather.
    This reduces wall-clock time from O(N × case_time) to O(max_case_time).
  - The checker now runs inside the Docker sandbox (via docker/run.py), eliminating
    the host-side exec() security vulnerability.
  - Early-exit semantics are preserved: CE/TLE/RE short-circuits remaining cases.
    However, all cases run concurrently; the first non-AC result in order is reported.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSessionLocal
from judge.pool import pool
from judge.runner import run_code, RunResult
from models import Problem, Submission, TestCase

logger = logging.getLogger(__name__)

# V1: language aliases — some problems store wrapper code under the canonical
# runtime name ('node' for JavaScript), so we try both keys.
_LANGUAGE_ALIASES: dict[str, list[str]] = {
    "javascript": ["javascript", "node"],
    "python3": ["python3", "python"],
    "rust": ["rust"],
}


def _get_wrapper(wrapper_code: dict, language: str) -> str:
    """
    Look up the wrapper for a given language, trying aliases if the primary key
    is not found.  Handles legacy 'node' keys stored for 'javascript' submissions.
    """
    if not isinstance(wrapper_code, dict):
        return ""
    for key in _LANGUAGE_ALIASES.get(language, [language]):
        if key in wrapper_code:
            return wrapper_code[key]
    return ""


def _comment_separator(language: str) -> str:
    """Return a language-appropriate comment separator for the judge harness."""
    # V2: use '//' for JS/Rust so the separator doesn't cause a syntax error
    if language in ("javascript", "rust"):
        return "// ─── JUDGE HARNESS (hidden) ───"
    return "# ─── JUDGE HARNESS (hidden) ───"


async def _judge_one_case(
    language: str,
    full_source: str,
    tc: TestCase,
    time_limit: float,
    memory_limit: int,
    checker_code: str,
) -> RunResult:
    """Run a single test case and return the RunResult."""
    return await run_code(
        pool=pool,
        language=language,
        source=full_source,
        stdin=tc.input,
        time_limit=time_limit,
        memory_limit=memory_limit,
        expected_output=tc.expected_output,
        checker_code=checker_code,
    )


async def judge_submission(submission_id: int) -> None:
    """
    Judge a submission against all test cases (called by the ARQ worker or BackgroundTasks).

    Opens its own DB session so it can be used outside the HTTP request lifecycle.
    """
    async with AsyncSessionLocal() as db:
        submission = await db.get(Submission, submission_id)
        if not submission:
            logger.warning("judge_submission: submission %d not found", submission_id)
            return

        problem = await db.get(Problem, submission.problem_id)
        if not problem:
            submission.status = "ERROR"
            await db.commit()
            return

        tc_result = await db.execute(
            select(TestCase)
            .where(TestCase.problem_id == problem.id)
            .order_by(TestCase.order_index)
        )
        test_cases = tc_result.scalars().all()

        if not test_cases:
            # No test cases configured → auto-accept
            submission.status = "DONE"
            submission.verdict = "AC"
            submission.score = 1.0
            await db.commit()
            return

        # Mark as judging
        submission.status = "JUDGING"
        submission.cases_total = len(test_cases)
        await db.commit()

        # Build full source (user code + hidden judge harness wrapper)
        # V1: use alias fallback so 'javascript' finds 'node' wrapper keys.
        wrapper = _get_wrapper(problem.wrapper_code, submission.language)
        if wrapper and wrapper.strip():
            # V2: language-appropriate separator prevents syntax errors.
            separator = _comment_separator(submission.language)
            full_source = (
                submission.source
                + f"\n\n{separator}\n"
                + wrapper
            )
        else:
            full_source = submission.source

        checker_code = problem.checker_code or ""

        try:
            # ── CE short-circuit ────────────────────────────────────────────
            # Run the first test case alone first.  If compilation fails (CE)
            # there is no point dispatching the remaining N-1 cases — they
            # would all compile the same broken source, wasting pool slots for
            # up to 30s each (Rust compile timeout).
            first_result = await _judge_one_case(
                submission.language,
                full_source,
                test_cases[0],
                problem.time_limit,
                problem.memory_limit,
                checker_code,
            )

            if first_result.verdict == "CE":
                # Fast path: mark done immediately, no further judging needed.
                submission.status = "DONE"
                submission.verdict = "CE"
                submission.cases_passed = 0
                submission.cases_total = len(test_cases)
                submission.score = 0.0
                submission.compile_error = first_result.stderr
                await db.commit()
                logger.info(
                    "Submission %d: CE on case 0, short-circuited %d remaining cases.",
                    submission_id,
                    len(test_cases) - 1,
                )
                return

            # ── Parallel judging for the rest ───────────────────────────────
            # First case already passed compilation; run remaining cases
            # concurrently.  Results from all cases (including case 0) are
            # collected in original order for accurate aggregation.
            remaining_tasks = [
                _judge_one_case(
                    submission.language,
                    full_source,
                    tc,
                    problem.time_limit,
                    problem.memory_limit,
                    checker_code,
                )
                for tc in test_cases[1:]
            ]
            rest_results: list[RunResult] = await asyncio.gather(*remaining_tasks)
            results: list[RunResult] = [first_result] + rest_results

        except Exception:
            logger.exception("Error while judging submission %d", submission_id)
            submission.status = "ERROR"
            await db.commit()
            return

        # ── Aggregate results ───────────────────────────────────────────────
        cases_passed = 0
        overall_verdict = "AC"
        max_time_ms = 0
        max_memory_kb = 0
        compile_error = None

        for run_result in results:
            max_time_ms = max(max_time_ms, run_result.time_ms)
            max_memory_kb = max(max_memory_kb, run_result.memory_kb)

            if run_result.verdict == "CE":
                if overall_verdict == "AC":
                    overall_verdict = "CE"
                    compile_error = run_result.stderr
            elif run_result.verdict in ("TLE", "RE", "WA"):
                if overall_verdict == "AC":
                    overall_verdict = run_result.verdict
            elif run_result.verdict == "AC":
                cases_passed += 1
            else:
                # V3: unknown verdict (e.g. unrecognised checker return) → WA,
                # not AC, to prevent a buggy checker from inflating scores.
                if overall_verdict == "AC":
                    overall_verdict = "WA"
                    logger.warning(
                        "Submission %d: unknown verdict %r from checker; treating as WA.",
                        submission_id, run_result.verdict,
                    )

        # Persist final result
        submission.status = "DONE"
        submission.verdict = overall_verdict
        submission.cases_passed = cases_passed
        submission.time_ms = max_time_ms
        submission.memory_peak_kb = max_memory_kb
        submission.score = cases_passed / len(test_cases)
        submission.compile_error = compile_error
        await db.commit()

        logger.info(
            "Submission %d judged: %s (%d/%d) in %dms",
            submission_id,
            overall_verdict,
            cases_passed,
            len(test_cases),
            max_time_ms,
        )
