"""Docker container pool — warm pool of pre-started judge containers."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import docker
import docker.errors

import os
from config import JUDGE_IMAGE, JUDGE_POOL_SIZE, SANDBOX_MEMORY_MB

logger = logging.getLogger(__name__)

LABEL_VALUE = os.environ.get("JUDGE_POOL_LABEL", "runner")


class ContainerPool:
    """
    Maintains a fixed-size pool of warm Docker containers.

    Each container is the custom bitcoin-oj-runner image running
    `sleep infinity`.  Submissions are executed via docker exec, not
    docker run, avoiding cold-start overhead.

    Tier 1 languages (Python, JS, Rust) all run in the same image.
    """

    def __init__(self, image: str = JUDGE_IMAGE, size: int = JUDGE_POOL_SIZE):
        self.image = image
        self.size = size
        self.concurrency_per_container = 1
        self._client: Optional[docker.DockerClient] = None
        self._queue: Optional[asyncio.Queue] = None
        self._containers: list = [None] * self.size
        self._locks: list[asyncio.Lock] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._client = docker.from_env()
        self._queue = asyncio.Queue(maxsize=self.size * self.concurrency_per_container)
        self._locks = [asyncio.Lock() for _ in range(self.size)]
        loop = asyncio.get_running_loop()

        logger.info("ContainerPool: cleaning up leftover containers…")
        await loop.run_in_executor(None, self._cleanup_old_containers)

        logger.info("ContainerPool: starting %d containers from %s…", self.size, self.image)
        for i in range(self.size):
            try:
                container = await loop.run_in_executor(None, self._create_container, i)
                self._containers[i] = container
                for _ in range(self.concurrency_per_container):
                    await self._queue.put(i)
                logger.info("ContainerPool: container %d/%d ready (%s)", i + 1, self.size, container.short_id)
            except Exception:
                logger.exception("ContainerPool: failed to create container %d", i)

        logger.info("ContainerPool: %d/%d containers ready.", self._queue.qsize(), self.size)

    async def stop(self) -> None:
        loop = asyncio.get_event_loop()
        for container in self._containers:
            try:
                await loop.run_in_executor(None, _stop_container, container)
            except Exception:
                pass
        self._containers.clear()
        logger.info("ContainerPool: all containers stopped.")

    # ── Acquire / release ─────────────────────────────────────────────────────

    @asynccontextmanager
    async def acquire(self, timeout: float = 10800.0):
        """
        Async context manager.  Yields a running container from the pool.
        On exit, returns the container to the pool (replacing if dead).
        """
        try:
            idx = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "All judge containers are busy — please retry in a moment."
            )

        healthy = True
        try:
            container = self._containers[idx]
            # Quick liveness check
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, container.reload)
            if container.status != "running":
                raise RuntimeError(f"Container {container.short_id} stopped unexpectedly")
            yield container
        except Exception:
            healthy = False
            raise
        finally:
            if not healthy:
                await self._replace_container(idx)
            else:
                await self._queue.put(idx)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _cleanup_old_containers(self) -> None:
        try:
            for c in self._client.containers.list(filters={"label": f"bitcoin-oj={LABEL_VALUE}"}):
                try:
                    c.stop(timeout=2)
                    c.remove(force=True)
                except Exception:
                    pass
        except Exception:
            pass

    def _stop_all_containers(self) -> None:
        for container in self._containers:
            try:
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception:
                pass
        self._containers.clear()

    def _create_container(self, index: int):
        name = f"bitcoin-oj-runner-{index}-{int(time.time())}"
        return self._client.containers.run(
            self.image,
            command="sleep infinity",
            detach=True,
            network_disabled=True,
            mem_limit=f"{SANDBOX_MEMORY_MB}m",
            nano_cpus=500_000_000,      # 0.5 vCPU
            read_only=True,
            tmpfs={"/tmp": "size=64m,exec,mode=1777"},
            labels={"bitcoin-oj": LABEL_VALUE},
            name=name,
        )

    async def _replace_container(self, idx: int) -> None:
        async with self._locks[idx]:
            dead_container = self._containers[idx]
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, dead_container.reload)
                if dead_container.status == "running":
                    # Another task already replaced or revived it
                    await self._queue.put(idx)
                    return
            except Exception:
                pass

            try:
                await loop.run_in_executor(None, _stop_container, dead_container)
            except Exception:
                pass
            
            try:
                loop2 = asyncio.get_running_loop()
                replacement = await loop2.run_in_executor(None, self._create_container, idx)
                self._containers[idx] = replacement
                await self._queue.put(idx)
                logger.warning("ContainerPool: replaced dead container with %s", replacement.short_id)
            except Exception:
                logger.exception("ContainerPool: failed to create replacement container!")
                # Put back index so it can be retried later, or it will permanently reduce pool size
                await self._queue.put(idx)


def _stop_container(c) -> None:
    try:
        c.stop(timeout=5)
        c.remove(force=True)
    except Exception:
        pass


# ── Singleton ─────────────────────────────────────────────────────────────────
pool = ContainerPool()
