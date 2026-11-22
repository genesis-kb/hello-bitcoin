#!/usr/bin/env python3
"""
Judge harness — runs INSIDE the Docker container.

Usage: python3 /judge/run.py
       The request is sent as a single line of JSON on stdin.

The request is read from stdin instead of a file or a command-line argument,
so submitted code cannot find it in /tmp or in /proc/<pid>/cmdline.

The harness must run as root (do not pass user= to docker exec). It starts the
submitted program as the unprivileged sandbox user and cleans up after it.

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
  sandbox_clean: true if no process or file of the sandbox user is left after
                 cleanup; if false, the container must be replaced, not reused
"""

import json
import os
import resource
import shutil
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


# Unprivileged user that submitted code runs as (created in Dockerfile.runner).
# The harness itself stays root so it can read the request, run the checker
# and clean up after the submission.
SANDBOX_UID = 10001
SANDBOX_GID = 10001


def _drop_privileges():
    """
    Switch the current (child) process from root to the sandbox user.

    The stdin/stdout/stderr pipes (fds 0-2) are created by root, so they are
    handed to the sandbox user first. Otherwise programs that open /dev/stdin
    or /dev/stdout by path, e.g. fs.readFileSync('/dev/stdin') in Node, fail
    with "permission denied".
    """
    for fd in (0, 1, 2):
        try:
            os.fchown(fd, SANDBOX_UID, SANDBOX_GID)
        except OSError:
            pass
    _become_sandbox_user()


def _become_sandbox_user():
    """
    Switch the current (child) process from root to the sandbox user.

    Used on its own for compilers and syntax checks: their fds are not handed
    over, since fd 0 there is not a pipe created for the child.
    """
    os.setgroups([])
    os.setgid(SANDBOX_GID)
    os.setuid(SANDBOX_UID)


def _make_preexec(memory_limit_mb: int):
    """Return a preexec_fn that applies RLIMIT_AS, starts a new session and drops root."""
    def preexec():
        # V2: memory limit applied here (child process), NOT to the compiler
        limit_bytes = memory_limit_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        except Exception:
            pass  # Unsupported on some platforms; container mem_limit still applies
        # V3: new process group so we can kill the whole tree on timeout
        os.setsid()
        _drop_privileges()
    return preexec


def _setsid_only():
    """preexec_fn for JS: new session and drop root, no RLIMIT_AS (V8 old-space is capped by --max-old-space-size)."""
    os.setsid()
    _drop_privileges()


# Locations the sandbox user can write to in the read-only runner container.
# /dev/mqueue holds POSIX message queues; unlinking a file there deletes the queue.
_SANDBOX_WRITABLE_DIRS = ("/tmp", "/dev/shm", "/dev/mqueue")


def _sandbox_pids():
    """
    PIDs of live (non-zombie) processes running as the sandbox user.

    The UIDs are read from /proc/<pid>/status (real, effective, saved and
    filesystem UID), not inferred from who owns the /proc/<pid> entries: the
    kernel can show those as root, e.g. for a process that made itself
    non-dumpable.
    """
    pids = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/status") as f:
                fields = dict(line.split(":", 1) for line in f if ":" in line)
            if str(SANDBOX_UID) not in fields["Uid"].split():
                continue
            if fields["State"].split()[0] == "Z":
                continue  # already dead, waiting to be reaped
            pids.append(int(pid))
        except (FileNotFoundError, ProcessLookupError, KeyError, IndexError):
            pass
    return pids


def _sandbox_paths():
    """Files and directories owned by the sandbox user, deepest first."""
    paths = []
    for top in _SANDBOX_WRITABLE_DIRS:
        for root, dirs, files in os.walk(top, topdown=False):
            for name in files + dirs:
                path = os.path.join(root, name)
                try:
                    if os.lstat(path).st_uid == SANDBOX_UID:
                        paths.append(path)
                except FileNotFoundError:
                    pass
    return paths


# /proc/sysvipc/<kind> lists the container's SysV IPC objects. These live in
# the kernel, not in a directory, so they survive the file cleanup above.
_SYSV_IPC_KINDS = ("shm", "msg", "sem")
_IPC_RMID = 0


def _sandbox_ipc():
    """SysV IPC objects (kind, id) created by or owned by the sandbox user."""
    objs = []
    for kind in _SYSV_IPC_KINDS:
        try:
            with open(f"/proc/sysvipc/{kind}") as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            continue
        cols = lines[0].split() if lines else []
        for row in lines[1:]:
            r = dict(zip(cols, row.split()))
            if str(SANDBOX_UID) in (r.get("uid"), r.get("cuid")):
                objs.append((kind, int(row.split()[1])))
    return objs


def _remove_ipc(objs) -> None:
    """
    Remove the given SysV IPC objects.

    Only the owner or creator may remove an IPC object (or CAP_SYS_ADMIN,
    which the container doesn't have), so even root gets EPERM here. The
    removal runs in a short-lived child that becomes the sandbox user.
    """
    if not objs:
        return
    pid = os.fork()
    if pid == 0:
        try:
            import ctypes
            _become_sandbox_user()
            libc = ctypes.CDLL(None)
            for kind, ipc_id in objs:
                if kind == "shm":
                    libc.shmctl(ipc_id, _IPC_RMID, None)
                elif kind == "msg":
                    libc.msgctl(ipc_id, _IPC_RMID, None)
                else:
                    libc.semctl(ipc_id, 0, _IPC_RMID)
        finally:
            os._exit(0)
    os.waitpid(pid, 0)


def _cleanup_sandbox() -> bool:
    """
    Kill every process the submission left behind and delete the files it wrote.

    Containers are reused across submissions. Without this, a process still
    running as the sandbox user (e.g. a child that left the process group with
    setsid), a file it wrote, or a SysV IPC object it created would still be
    there for the next submission.

    Returns True if nothing owned by the sandbox user is left.
    """
    for _ in range(10):
        pids = _sandbox_pids()
        if not pids:
            break
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.05)

    for path in _sandbox_paths():
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except FileNotFoundError:
            pass

    # After the processes are gone, so nothing recreates them meanwhile.
    _remove_ipc(_sandbox_ipc())

    return not _sandbox_pids() and not _sandbox_paths() and not _sandbox_ipc()


def main():
    # V1: the request (including expected_output and checker_code) arrives on
    # stdin, so it is never written to /tmp or shown in a process command line.
    try:
        req = json.loads(sys.stdin.readline())
    except Exception as e:
        _out("RE", stderr=f"Harness: failed to read request from stdin: {e}")
        return

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
        # The program runs as the sandbox user, which must be able to read the
        # source and write to its working directory.
        os.chown(tmpdir, SANDBOX_UID, SANDBOX_GID)

        # ── Compile if needed ─────────────────────────────────────────────────
        # Compilation runs WITHOUT memory limits (rustc needs more than 256 MB),
        # but as the sandbox user, like the program itself.
        if language == "rust":
            bin_path = os.path.join(tmpdir, "solution")
            try:
                cr = subprocess.run(
                    ["rustc", src_path, "-o", bin_path, "--edition", "2021"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    # Not root: include_str!/include_bytes! read files at compile time
                    preexec_fn=_become_sandbox_user,
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
            chk = subprocess.run(["python3", "-m", "py_compile", src_path], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, preexec_fn=_become_sandbox_user)
            if chk.returncode != 0:
                _out("CE", stderr=chk.stderr[:4096])
                return
            cmd = ["python3", "-u", src_path]

        elif language == "javascript":
            # Syntax check first
            chk = subprocess.run(["node", "--check", src_path], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, preexec_fn=_become_sandbox_user)
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
                # V3: kill the entire process group (catches forked children).
                # Children that left the group with setsid are killed by
                # _cleanup_sandbox() after the run.
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


# The result is printed only after the sandbox cleanup, so it can also report
# whether the cleanup succeeded.
_RESULT: dict = {}


def _out(verdict, stdout="", stderr="", time_ms=0, exit_code=0, memory_kb=0, checker_msg=""):
    """Record the result of this run. It is printed as JSON when the harness exits."""
    _RESULT.update({
        "verdict": verdict,
        "stdout": stdout,
        "stderr": stderr,
        "time_ms": time_ms,
        "exit_code": exit_code,
        "memory_kb": memory_kb,
        "checker_msg": checker_msg,
    })


if __name__ == "__main__":
    try:
        main()
    finally:
        # Clean up even if main() failed, and always print exactly one result.
        clean = _cleanup_sandbox()
        if not _RESULT:
            _out("RE", stderr="Harness: no result produced.")
        _RESULT["sandbox_clean"] = clean
        print(json.dumps(_RESULT), flush=True)
