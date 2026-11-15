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
from judge.runner import RunResult, _exec_code

SANDBOX_UID = 10001

# Prints the PIDs of live (non-zombie) processes owned by the sandbox user.
# Run as root with docker exec; the runner image has no ps or pgrep.
_LIST_SANDBOX_PROCS = (
    "import os\n"
    "for p in os.listdir('/proc'):\n"
    "    if not p.isdigit():\n"
    "        continue\n"
    "    try:\n"
    f"        if os.stat('/proc/' + p).st_uid != {SANDBOX_UID}:\n"
    "            continue\n"
    "        if open('/proc/' + p + '/stat').read().rsplit(')', 1)[1].split()[0] != 'Z':\n"
    "            print(p)\n"
    "    except Exception:\n"
    "        pass\n"
)


@pytest.fixture(scope="module")
def container():
    """One runner container, created like the pool creates them, shared by all sandbox tests."""
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.images.get("hello-bitcoin-runner")
    except Exception as exc:
        pytest.skip(f"Docker or the hello-bitcoin-runner image is not available: {exc}")
    pool = ContainerPool()
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
        "print('ok')\n"
    )
    assert run(container, first, expected_output="ok").verdict == "AC"

    second = (
        "import os\n"
        "names = []\n"
        "for top in ('/tmp', '/dev/shm'):\n"
        "    for root, dirs, files in os.walk(top):\n"
        "        names += dirs + files\n"
        "print('listing: ' + ' '.join(names))\n"
    )
    res = run(container, second)
    # The listing includes this run's own work directory, so the verdict is WA;
    # check that the listing actually ran before trusting the "not in".
    assert res.exit_code == 0 and res.stdout.startswith("listing:"), res.stderr
    assert "leftover_from_run1" not in res.stdout


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
