#!/usr/bin/env python3
"""
Judge harness — runs INSIDE the Docker container.

Usage: python3 /judge/run.py /tmp/req.json

Input JSON fields:
  language        : "python3" | "javascript" | "rust"
  source          : source code string
  stdin           : input to pipe to the program
  time_limit      : float, seconds
  memory_limit    : int, MB
  expected_output : str  (required for checker)
  checker_code    : str  (optional; falls back to exact-match if absent)

Output JSON fields:
  verdict      : "AC" | "WA" | "TLE" | "RE" | "CE"
  stdout       : captured stdout (truncated to 256 KiB)
  stderr       : captured stderr (truncated to 2048 chars)
  time_ms      : wall-clock milliseconds
  exit_code    : process exit code
  memory_kb    : peak RSS in KB (measured via resource.getrusage)
  checker_msg  : human-readable message from the checker
"""

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
import time


# ── Default checker (exact-match, strip whitespace) ───────────────────────────

_DEFAULT_CHECKER = """\
def check(test_input: str, user_output: str, expected_output: str) -> dict:
    user_lines = [l.strip() for l in user_output.strip().splitlines()]
    exp_lines  = [l.strip() for l in expected_output.strip().splitlines()]
    if user_lines == exp_lines:
        return {"verdict": "AC", "score": 1.0, "message": "Correct"}
    for i, (u, e) in enumerate(zip(user_lines, exp_lines)):
        if u != e:
            return {"verdict": "WA", "score": 0.0,
                    "message": f"Line {i+1}: expected {e!r}, got {u!r}"}
    return {"verdict": "WA", "score": 0.0,
            "message": f"Expected {len(exp_lines)} lines, got {len(user_lines)} lines."}
"""

# V4: cap stdout so unbounded output cannot exhaust the harness
_MAX_STDOUT_BYTES = 256 * 1024  # 256 KiB


def run_checker(checker_code: str, test_input: str, user_output: str, expected_output: str) -> dict:
    """
    Execute the checker program.

    The checker runs INSIDE this sandboxed container — no exec() on the host.
    The checker_code must define:
        def check(test_input, user_output, expected_output) -> dict
    """
    code = checker_code.strip() if checker_code and checker_code.strip() else _DEFAULT_CHECKER
    namespace: dict = {}
    try:
        exec(compile(code, "<checker>", "exec"), namespace)  # safe: runs inside sandbox
        check_fn = namespace.get("check")
        if not callable(check_fn):
            raise ValueError("Checker must define a callable 'check' function.")
        result = check_fn(test_input, user_output, expected_output)
        if not isinstance(result, dict) or "verdict" not in result:
            raise ValueError(f"Checker returned invalid result: {result!r}")
        return result
    except Exception as exc:
        return {"verdict": "WA", "score": 0.0, "message": f"Checker error: {exc}"}


def _make_preexec(memory_limit_mb: int):
    """Return a preexec_fn that applies RLIMIT_AS and creates a new process group."""
    def preexec():
        # V2: memory limit applied here (child process), NOT to the compiler
        limit_bytes = memory_limit_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        except Exception:
            pass  # Unsupported on some platforms; container mem_limit still applies
        # V3: new process group so we can kill the whole tree on timeout
        os.setsid()
    return preexec


def _setsid_only():
    """preexec_fn for JS (memory managed by --max-old-space-size, not RLIMIT_AS)."""
    os.setsid()


def main():
    if len(sys.argv) < 2:
        _out("RE", stderr="Harness: no input file specified.")
        return

    req_file = sys.argv[1]
    try:
        with open(req_file) as f:
            req = json.load(f)
    except Exception as e:
        _out("RE", stderr=f"Harness: failed to read input: {e}")
        return
    finally:
        # V1: delete the request file immediately so submitted code cannot
        # enumerate /tmp and read expected_output / checker_code.
        try:
            os.remove(req_file)
        except Exception:
            pass

    language        = req.get("language", "python3")
    source          = req.get("source", "")
    stdin_data      = req.get("stdin", "")
    time_limit      = float(req.get("time_limit", 5.0))
    memory_limit_mb = int(req.get("memory_limit", 256))
    expected_output = req.get("expected_output", "")
    checker_code    = req.get("checker_code", "")

    # V2: memory limit is applied only to the executed solution via preexec_fn,
    # NOT to the compiler (rustc needs ~400–800 MB; applying the limit here
    # would cause valid Rust submissions to get CE).

    with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
        ext_map = {"python3": "py", "javascript": "js", "rust": "rs"}
        ext = ext_map.get(language, "py")
        src_path = os.path.join(tmpdir, f"solution.{ext}")

        with open(src_path, "w") as f:
            f.write(source)

        # ── Compile if needed ─────────────────────────────────────────────────
        # Compilation runs WITHOUT memory limits (rustc needs more than 256 MB)
        if language == "rust":
            bin_path = os.path.join(tmpdir, "solution")
            try:
                cr = subprocess.run(
                    ["rustc", src_path, "-o", bin_path, "--edition", "2021"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                _out("CE", stderr="Compilation timed out (>30s).")
                return
            if cr.returncode != 0:
                _out("CE", stderr=cr.stderr[:4096])
                return
            cmd = [bin_path]

        elif language == "python3":
            # Syntax check first
            chk = subprocess.run(["python3", "-m", "py_compile", src_path], capture_output=True, text=True)
            if chk.returncode != 0:
                _out("CE", stderr=chk.stderr[:4096])
                return
            cmd = ["python3", "-u", src_path]

        elif language == "javascript":
            # Syntax check first
            chk = subprocess.run(["node", "--check", src_path], capture_output=True, text=True)
            if chk.returncode != 0:
                _out("CE", stderr=chk.stderr[:4096])
                return
            cmd = ["node", f"--max-old-space-size={memory_limit_mb}", src_path]

        else:
            _out("RE", stderr=f"Unsupported language: {language}")
            return

        # ── Execute ───────────────────────────────────────────────────────────
        # V2: memory limit applied via preexec_fn, after compilation.
        # V3: use Popen + process group so we can SIGKILL the whole tree on timeout.
        if language == "javascript":
            preexec = _setsid_only
        else:
            preexec = _make_preexec(memory_limit_mb)

        start = time.monotonic()
        timed_out = False
        stdin_bytes = stdin_data.encode() if isinstance(stdin_data, str) else stdin_data
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmpdir,
                preexec_fn=preexec,
            )
            try:
                raw_stdout, raw_stderr = proc.communicate(
                    input=stdin_bytes,
                    timeout=time_limit,
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                # V3: kill the entire process group (catches forked children)
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
                proc.wait()
                raw_stdout, raw_stderr = b"", b""
        except Exception as exc:
            _out("RE", stderr=f"Harness: failed to exec process: {exc}")
            return

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if timed_out:
            _out("TLE", stderr=f"Time limit exceeded ({time_limit}s).",
                 time_ms=int(time_limit * 1000))
            return

        # V4: truncate stdout to 256 KiB before passing to checker / output
        if len(raw_stdout) > _MAX_STDOUT_BYTES:
            raw_stdout = raw_stdout[:_MAX_STDOUT_BYTES]

        stdout_text = raw_stdout.decode("utf-8", errors="replace")
        stderr_text = raw_stderr.decode("utf-8", errors="replace")

        # ── Measure peak memory (best-effort) ────────────────────────────────
        try:
            # RUSAGE_CHILDREN captures children that have finished
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            memory_kb = usage.ru_maxrss  # KB on Linux, bytes on macOS
            import platform
            if platform.system() == "Darwin":
                memory_kb = memory_kb // 1024
        except Exception:
            memory_kb = 0

        if proc.returncode != 0:
            _out("RE", stdout=stdout_text, stderr=stderr_text[:2048],
                 time_ms=elapsed_ms, exit_code=proc.returncode, memory_kb=memory_kb)
            return

        # ── Run checker inside the sandbox ───────────────────────────────────
        checker_result = run_checker(checker_code, stdin_data, stdout_text, expected_output)
        verdict = checker_result.get("verdict", "WA")

        _out(
            verdict,
            stdout=stdout_text,
            stderr=stderr_text[:2048],
            time_ms=elapsed_ms,
            exit_code=proc.returncode,
            memory_kb=memory_kb,
            checker_msg=checker_result.get("message", ""),
        )


def _out(verdict, stdout="", stderr="", time_ms=0, exit_code=0, memory_kb=0, checker_msg=""):
    print(json.dumps({
        "verdict": verdict,
        "stdout": stdout,
        "stderr": stderr,
        "time_ms": time_ms,
        "exit_code": exit_code,
        "memory_kb": memory_kb,
        "checker_msg": checker_msg,
    }), flush=True)


if __name__ == "__main__":
    main()
