"""Judge runner — executes user code in a container from the pool."""

import asyncio
import json
import logging
from dataclasses import dataclass

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
    # True only when the harness confirmed nothing of the submission survived
    # its cleanup. Anything else means the container should not be reused.
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
    Run the judge harness and send it the request on stdin.

    Unlike putting the request in the exec command (sh -c 'echo <base64> ...'),
    stdin never shows up in /proc/<pid>/cmdline, where submitted code could read
    the source, expected output and checker of a run.
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
            chunk = raw.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    return _demux(b"".join(chunks))

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

    The request (with expected output and checker code) goes to run.py on
    stdin, so it is never written to /tmp or visible in a process command line.
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
        req_json = json.dumps(request).encode("utf-8")  # one line: json.dumps escapes newlines

        raw_stdout, raw_stderr = _exec_harness(container, req_json)

        text = raw_stdout.decode("utf-8", errors="replace")
        json_start = text.find("{")
        if json_start == -1:
            err = raw_stderr.decode("utf-8", errors="replace")
            return RunResult("RE", stderr=f"Harness produced no JSON. Raw: {(text + err)[:300]}")

        result, _ = json.JSONDecoder().raw_decode(text[json_start:])
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
        # V3: enforce async deadline on exec_run with wait_for
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
            # Something of this submission may still be in the container
            # (or we couldn't confirm it isn't); don't hand it to the next run.
            pool.mark_tainted(container)
        return result
