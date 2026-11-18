"""Judge runner — executes user code in a container from the pool."""

import asyncio
import json
import logging
from dataclasses import dataclass

from docker.utils.socket import NPIPE_ENDED

from .pool import ContainerPool

logger = logging.getLogger(__name__)

# Hard deadline for the entire docker exec (compile + run + check).
# Must exceed: time_limit + compile timeout (30s) + checker overhead.
_EXEC_DEADLINE_SECONDS = 120.0


@dataclass
class RunResult:
    verdict: str            # AC | WA | TLE | RE | CE
    stdout: str = ""
    stderr: str = ""
    time_ms: int = 0
    exit_code: int = 0
    memory_kb: int = 0
    checker_msg: str = ""
    # True only if the harness confirmed that nothing from the submission is
    # left after its cleanup. Otherwise the container must not be reused.
    sandbox_clean: bool = False


# ── Blocking executor (called inside thread pool) ─────────────────────────────

def _demux(data: bytes) -> tuple[bytes, bytes]:
    """Split Docker's multiplexed exec stream (8-byte frame headers) into stdout/stderr."""
    out, err, i = bytearray(), bytearray(), 0
    while i + 8 <= len(data):
        stream, size = data[i], int.from_bytes(data[i + 4:i + 8], "big")
        (err if stream == 2 else out).extend(data[i + 8:i + 8 + size])
        i += 8 + size
    return bytes(out), bytes(err)


def _exec_harness(container, payload: bytes) -> tuple[bytes, bytes]:
    """
    Run the judge harness in the container and send it the request on stdin.

    The request is not put in the exec command, because a process's command
    line is readable by other processes in /proc/<pid>/cmdline, and that would
    let submitted code read the expected output and checker. Stdin is not
    exposed that way.

    Returns the harness's (stdout, stderr).
    """
    api = container.client.api
    exec_id = api.exec_create(
        container.id, ["python3", "/judge/run.py"],
        stdin=True, stdout=True, stderr=True,
    )["Id"]
    sock = api.exec_start(exec_id, socket=True)
    raw = getattr(sock, "_sock", sock)
    raw.settimeout(_EXEC_DEADLINE_SECONDS)
    try:
        raw.sendall(payload + b"\n")  # run.py reads exactly one line
        chunks = []
        while True:
            try:
                chunk = raw.recv(65536)
            except Exception as e:
                # On Windows the Docker connection is a named pipe, which
                # signals end of output with an error instead of b"".
                if e.args and e.args[0] == NPIPE_ENDED:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    return _demux(b"".join(chunks))


def _parse_harness_result(text: str):
    """
    Return the harness's result dict from its stdout, or None.

    run.py prints its result as the final line of stdout. A checker can print
    to stdout too (it runs in the harness process), so we can't just take the
    first '{' — a JSON-shaped diagnostic from the checker would be parsed as the
    result and could flip the verdict. Instead, scan from the last line and take
    the last JSON object that looks like a result (has a "verdict").
    """
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and "verdict" in obj:
            return obj
    return None


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

    The request (including the expected output and checker code) is sent to
    run.py on stdin, so it is never written to /tmp or shown in a process
    command line.
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
        # json.dumps escapes newlines, so the request is always a single line
        req_json = json.dumps(request).encode("utf-8")

        raw_stdout, raw_stderr = _exec_harness(container, req_json)

        text = raw_stdout.decode("utf-8", errors="replace")
        result = _parse_harness_result(text)
        if result is None:
            err = raw_stderr.decode("utf-8", errors="replace")
            return RunResult("RE", stderr=f"Harness produced no result JSON. Raw: {(text + err)[:300]}")

        return RunResult(
            verdict=result.get("verdict", "RE"),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", ""),
            time_ms=result.get("time_ms", 0),
            exit_code=result.get("exit_code", 0),
            memory_kb=result.get("memory_kb", 0),
            checker_msg=result.get("checker_msg", ""),
            sandbox_clean=result.get("sandbox_clean") is True,
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
        # V3: enforce an overall deadline on the exec with wait_for
        result = await asyncio.wait_for(
            loop.run_in_executor(
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
            ),
            timeout=_EXEC_DEADLINE_SECONDS,
        )
        if not result.sandbox_clean:
            # Something from this submission may still be in the container, or
            # the harness couldn't confirm it isn't. Don't reuse it for the next run.
            pool.mark_tainted(container)
        return result
