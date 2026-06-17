"""Judge runner — executes user code in a container from the pool."""

import asyncio
import base64
import json
import logging
import uuid
from dataclasses import dataclass

from .pool import ContainerPool

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    verdict: str            # AC | WA | TLE | RE | CE
    stdout: str = ""
    stderr: str = ""
    time_ms: int = 0
    exit_code: int = 0
    memory_kb: int = 0
    checker_msg: str = ""


# ── Blocking executor (called inside thread pool) ─────────────────────────────

def _exec_code(
    container,
    language: str,
    source: str,
    stdin: str,
    time_limit: float,
    memory_limit: int,
    expected_output: str,
    checker_code: str,
) -> RunResult:
    """
    Blocking function — run inside asyncio.run_in_executor().

    The full request (including checker_code and expected_output) is sent to
    the Docker container so the checker executes inside the sandbox, never on
    the host process.
    """
    try:
        request = {
            "language": language,
            "source": source,
            "stdin": stdin,
            "time_limit": time_limit,
            "memory_limit": memory_limit,
            "expected_output": expected_output,
            "checker_code": checker_code,
        }
        req_json = json.dumps(request).encode("utf-8")
        req_b64 = base64.b64encode(req_json).decode("ascii")

        req_id = uuid.uuid4().hex
        req_file = f"/tmp/{req_id}.json"

        # Inject JSON via base64 to avoid put_archive failing on tmpfs
        cmd = (
            f"sh -c 'echo {req_b64} | base64 -d > {req_file} "
            f"&& python3 /judge/run.py {req_file}; rm -f {req_file}'"
        )

        exit_code, raw_output = container.exec_run(
            cmd,
            stdout=True,
            stderr=True,
            demux=False,
        )

        if raw_output is None:
            raw_output = b""

        text = raw_output.decode("utf-8", errors="replace")
        json_start = text.find("{")
        if json_start == -1:
            return RunResult("RE", stderr=f"Harness produced no JSON. Raw: {text[:300]}")

        result = json.loads(text[json_start:])
        return RunResult(
            verdict=result.get("verdict", "RE"),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            time_ms=result.get("time_ms", 0),
            exit_code=result.get("exit_code", exit_code or 0),
            memory_kb=result.get("memory_kb", 0),
            checker_msg=result.get("checker_msg", ""),
        )

    except Exception as e:
        logger.exception("Runner: unexpected error during exec")
        return RunResult("RE", stderr=str(e))


# ── Async entry point ─────────────────────────────────────────────────────────

async def run_code(
    pool: ContainerPool,
    language: str,
    source: str,
    stdin: str,
    time_limit: float = 5.0,
    memory_limit: int = 256,
    expected_output: str = "",
    checker_code: str = "",
) -> RunResult:
    """Acquire a container from the pool and run code + checker asynchronously."""
    loop = asyncio.get_running_loop()  # Correct API for Python 3.10+
    async with pool.acquire() as container:
        result = await loop.run_in_executor(
            None,
            _exec_code,
            container,
            language,
            source,
            stdin,
            time_limit,
            memory_limit,
            expected_output,
            checker_code,
        )
        return result
