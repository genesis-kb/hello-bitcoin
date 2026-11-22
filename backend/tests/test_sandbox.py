"""
Regression tests for judge sandbox isolation (issue #3).

The sandbox tests run real submissions through the harness in a runner
container created with the same settings as the production pool. All of them
share one container, so anything a run leaves behind would show up in a later
test. (Unlike the pool, the fixture keeps the container even after an unclean
run; the tests assert sandbox_clean instead.) They need Docker and the
hello-bitcoin-runner image, and are skipped if either is missing.

The pool tests at the end use fake containers and need no Docker.
"""

import asyncio
import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JUDGE_POOL_LABEL", "test-sandbox")

import pytest

from judge import runner
from judge.pool import ContainerPool
from judge.runner import RunResult, _exec_code, _parse_harness_result

SANDBOX_UID = 10001

# Prints the PIDs of live (non-zombie) processes running as the sandbox user.
# Run as root with docker exec; the runner image has no ps or pgrep.
# Reads the real UIDs from /proc/<pid>/status, not the owner of /proc/<pid>,
# which shows root for a process that made itself non-dumpable.
_LIST_SANDBOX_PROCS = (
    "import os\n"
    "for p in os.listdir('/proc'):\n"
    "    if not p.isdigit():\n"
    "        continue\n"
    "    try:\n"
    "        f = dict(l.split(':', 1) for l in open('/proc/' + p + '/status') if ':' in l)\n"
    f"        if '{SANDBOX_UID}' in f['Uid'].split() and f['State'].split()[0] != 'Z':\n"
    "            print(p)\n"
    "    except Exception:\n"
    "        pass\n"
)

# Prints SysV IPC objects (shared memory, message queues, semaphores) created
# by or owned by the sandbox user, as "<kind> <id>".
_LIST_SANDBOX_IPC = (
    "for kind in ('shm', 'msg', 'sem'):\n"
    "    lines = open('/proc/sysvipc/' + kind).read().splitlines()\n"
    "    cols = lines[0].split()\n"
    "    for row in lines[1:]:\n"
    "        r = dict(zip(cols, row.split()))\n"
    f"        if '{SANDBOX_UID}' in (r['uid'], r['cuid']):\n"
    "            print(kind, row.split()[1])\n"
)


@pytest.fixture(scope="module")
def container():
    """One runner container, created like the pool creates them, shared by all sandbox tests."""
    docker = pytest.importorskip("docker")
    pool = ContainerPool()
    try:
        client = docker.from_env()
        client.images.get(pool.image)  # the image the pool (and this fixture) will actually run
    except Exception as exc:
        pytest.skip(f"Docker or the {pool.image} image is not available: {exc}")
    pool._client = client
    c = pool._create_container(0)
    yield c
    c.remove(force=True)


def run(container, source, expected_output="", stdin="", time_limit=2.0, checker_code=""):
    """Judge a Python submission in the container and return the RunResult."""
    return _exec_code(container, "python3", source, stdin, time_limit, 256, expected_output, checker_code)


def sandbox_procs(container):
    """PIDs of sandbox-user processes still alive in the container."""
    _, out = container.exec_run(["python3", "-c", _LIST_SANDBOX_PROCS])
    return out.decode().split()


def sandbox_ipc(container):
    """SysV IPC objects of the sandbox user still present in the container."""
    _, out = container.exec_run(["python3", "-c", _LIST_SANDBOX_IPC])
    return out.decode().splitlines()


def test_submission_does_not_run_as_root(container):
    """Submitted code runs as the sandbox user, not root."""
    res = run(container, "import os\nprint(os.getuid())", expected_output=str(SANDBOX_UID))
    assert res.stdout.strip() == str(SANDBOX_UID)
    assert res.verdict == "AC"
    assert res.sandbox_clean


def test_dev_stdin_and_stdout_still_work(container):
    """Dropping root does not break programs that open /dev/stdin or /dev/stdout by path."""
    source = (
        "data = open('/dev/stdin').read().split()\n"
        "with open('/dev/stdout', 'w') as out:\n"
        "    out.write(str(int(data[0]) + int(data[1])) + '\\n')\n"
    )
    res = run(container, source, stdin="1 2\n", expected_output="3")
    assert res.verdict == "AC", res.stderr


def test_request_is_not_visible_to_the_submission(container):
    """The expected output is not in any process's command line, or in the environment of any process the submission can read."""
    marker = "SECRET_EXPECTED_7f3a"
    # The submission builds the marker from two halves, so the marker never
    # appears in its own source code (which is also in the request).
    source = (
        "import os\n"
        "marker = ('SECRET_' + 'EXPECTED_7f3a').encode()\n"
        "found = []\n"
        "for p in os.listdir('/proc'):\n"
        "    if not p.isdigit():\n"
        "        continue\n"
        "    for f in ('cmdline', 'environ'):\n"
        "        try:\n"
        "            if marker in open('/proc/' + p + '/' + f, 'rb').read():\n"
        "                found.append(p + '/' + f)\n"
        "        except Exception:\n"
        "            pass\n"
        "print('LEAK ' + ' '.join(found) if found else 'clean')\n"
    )
    res = run(container, source, expected_output=marker)
    assert res.stdout.strip() == "clean", res.stdout


def test_detached_child_is_killed_after_timeout(container):
    """
    A child that left the process group with setsid is killed after a timeout.

    The child keeps stdout open, so the run times out. Killing the process
    group alone doesn't reach it, because it is in its own session.
    """
    source = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"
        "    time.sleep(300)\n"
        "print('parent done')\n"
    )
    res = run(container, source, expected_output="parent done", time_limit=1.0)
    assert res.verdict == "TLE"
    assert sandbox_procs(container) == []
    assert res.sandbox_clean


def test_detached_child_is_killed_after_normal_exit(container):
    """
    A detached child is killed even when the run ends normally.

    The parent exits normally, and the child detaches from stdio and keeps
    running. Nothing used to clean up after a run that didn't time out.
    """
    source = (
        "import os, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"
        "    fd = os.open(os.devnull, os.O_RDWR)\n"
        "    for i in (0, 1, 2):\n"
        "        os.dup2(fd, i)\n"
        "    time.sleep(300)\n"
        "    os._exit(0)\n"
        "print('parent done')\n"
    )
    res = run(container, source, expected_output="parent done")
    assert res.verdict == "AC"
    assert sandbox_procs(container) == []
    assert res.sandbox_clean


def test_files_do_not_survive_to_the_next_submission(container):
    """Files one run writes to /tmp or /dev/shm are gone by the next run."""
    first = (
        "open('/tmp/leftover_from_run1', 'w').write('x')\n"
        "open('/dev/shm/leftover_from_run1', 'w').write('x')\n"
        "open('/dev/mqueue/leftover_from_run1', 'w').close()  # creates a POSIX message queue\n"
        "print('ok')\n"
    )
    assert run(container, first, expected_output="ok").verdict == "AC"

    second = (
        "import os\n"
        "names = []\n"
        "for top in ('/tmp', '/dev/shm', '/dev/mqueue'):\n"
        "    for root, dirs, files in os.walk(top):\n"
        "        names += dirs + files\n"
        "print('listing: ' + ' '.join(names))\n"
    )
    res = run(container, second)
    # The listing includes this run's own work directory, so the verdict is WA;
    # check that the listing actually ran before trusting the "not in".
    assert res.exit_code == 0 and res.stdout.startswith("listing:"), res.stderr
    assert "leftover_from_run1" not in res.stdout


def test_non_dumpable_detached_child_is_killed(container):
    """
    A detached child is killed even if it made itself non-dumpable.

    A non-dumpable process's /proc/<pid> is owned by root, so the cleanup
    must not decide whose process it is from the owner of /proc/<pid>.
    """
    source = (
        "import ctypes, os, time\n"
        "if os.fork() == 0:\n"
        "    os.setsid()\n"
        "    ctypes.CDLL(None).prctl(4, 0)  # PR_SET_DUMPABLE = 4\n"
        "    fd = os.open(os.devnull, os.O_RDWR)\n"
        "    for i in (0, 1, 2):\n"
        "        os.dup2(fd, i)\n"
        "    time.sleep(300)\n"
        "    os._exit(0)\n"
        "print('parent done')\n"
    )
    res = run(container, source, expected_output="parent done")
    assert res.verdict == "AC"
    assert sandbox_procs(container) == []
    assert res.sandbox_clean


def test_sysv_ipc_objects_do_not_survive(container):
    """SysV shared memory, message queues and semaphores a run creates are removed after it."""
    source = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None)\n"
        "IPC_CREAT = 0o1000\n"
        "ids = [libc.shmget(0, 4096, IPC_CREAT | 0o600),\n"
        "       libc.msgget(0, IPC_CREAT | 0o600),\n"
        "       libc.semget(0, 1, IPC_CREAT | 0o600)]\n"
        "print('ok' if min(ids) >= 0 else 'create failed')\n"
    )
    res = run(container, source, expected_output="ok")
    assert res.verdict == "AC", res.stdout + res.stderr  # the objects really were created
    assert sandbox_ipc(container) == []
    assert res.sandbox_clean


def test_compiler_does_not_run_as_root(container):
    """
    rustc runs as the sandbox user, so a submission can't embed a root-only
    file at compile time with include_str!.
    """
    source = 'const S: &str = include_str!("/etc/shadow");\nfn main() { println!("{}", S.len()); }\n'
    res = _exec_code(container, "rust", source, "", 2.0, 256, "", "")
    assert res.verdict == "CE"
    assert "Permission denied" in res.stderr or "permission denied" in res.stderr.lower(), res.stderr


# ── Pool: containers the harness couldn't confirm clean are replaced ──────────

class _FakeContainer:
    """Minimal stand-in for a docker container, enough for ContainerPool.acquire()."""

    def __init__(self, cid):
        self.id = cid
        self.short_id = cid
        self.status = "running"
        self.stopped = False

    def reload(self):
        pass

    def stop(self, timeout=None):
        self.stopped = True
        self.status = "exited"

    def remove(self, force=False):
        pass


def _pool_with(first):
    """A one-slot pool holding `first`, whose replacements are fake containers named 'replacement'."""
    p = ContainerPool(size=1)
    p._queue = asyncio.Queue()
    p._locks = [asyncio.Lock()]
    p._containers = [first]
    p._create_container = lambda idx: _FakeContainer("replacement")
    return p


def test_pool_recycles_tainted_container():
    """A container marked tainted is stopped and replaced when released."""
    first = _FakeContainer("first")

    async def scenario():
        p = _pool_with(first)
        await p._queue.put(0)
        async with p.acquire() as c:
            p.mark_tainted(c)
        return p

    p = asyncio.run(scenario())
    assert first.stopped
    assert p._containers[0].id == "replacement"
    assert p._queue.qsize() == 1


def test_harness_result_parsed_from_last_line_not_checker_output():
    """A JSON-shaped line printed by the checker before the result must not be read as the result."""
    text = (
        '{"note": "checker debug", "verdict": "AC"}\n'   # looks like a result, but isn't the last one
        '{"verdict": "WA", "stdout": "", "sandbox_clean": true}\n'
    )
    result = _parse_harness_result(text)
    assert result["verdict"] == "WA"
    assert result["sandbox_clean"] is True


def test_pool_reuses_clean_container():
    """A container that wasn't marked tainted goes back to the pool unchanged."""
    first = _FakeContainer("first")

    async def scenario():
        p = _pool_with(first)
        await p._queue.put(0)
        async with p.acquire():
            pass
        return p

    p = asyncio.run(scenario())
    assert not first.stopped
    assert p._containers[0] is first


@pytest.mark.parametrize("clean", [False, True])
def test_run_code_recycles_container_only_when_harness_reports_unclean(monkeypatch, clean):
    """run_code replaces the container when the harness reports sandbox_clean=False, and keeps it otherwise."""
    first = _FakeContainer("first")
    monkeypatch.setattr(runner, "_exec_code", lambda *args: RunResult("AC", sandbox_clean=clean))

    async def scenario():
        p = _pool_with(first)
        await p._queue.put(0)
        await runner.run_code(p, "python3", "print(1)", "")
        return p

    p = asyncio.run(scenario())
    assert first.stopped is not clean
    assert p._containers[0].id == ("first" if clean else "replacement")
    assert p._queue.qsize() == 1


def test_pool_replaces_container_when_run_is_cancelled():
    """A cancelled run (e.g. an ARQ job timeout) may still be executing, so its container is replaced."""
    first = _FakeContainer("first")

    async def scenario():
        p = _pool_with(first)
        await p._queue.put(0)
        acquired = asyncio.Event()

        async def job():
            async with p.acquire():
                acquired.set()
                await asyncio.sleep(10)

        task = asyncio.ensure_future(job())
        await asyncio.wait_for(acquired.wait(), timeout=5)  # cancel only while the container is held
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return p

    p = asyncio.run(scenario())
    assert first.stopped
    assert p._containers[0].id == "replacement"
    assert p._queue.qsize() == 1
