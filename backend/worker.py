"""ARQ worker — processes judging jobs from the Redis queue."""

import logging

from arq.connections import RedisSettings

from config import JUDGE_POOL_SIZE, REDIS_URL
from db import AsyncSessionLocal
from judge.pool import pool
from services.judging import judge_submission

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


async def startup(ctx):
    logger.info("Worker startup: starting container pool...")
    await pool.start()
    ctx["pool"] = pool

    # V3: cap concurrency to the actual number of ready containers, not the
    # configured target. Fail startup if none started (prevents silently
    # accepting jobs that will never be processed).
    ready = pool._queue.qsize()
    if ready == 0:
        raise RuntimeError(
            "ContainerPool: no containers started successfully — aborting worker startup."
        )
    if ready < JUDGE_POOL_SIZE:
        logger.warning(
            "ContainerPool: only %d/%d containers ready; capping max_jobs to %d.",
            ready, JUDGE_POOL_SIZE, ready,
        )
    WorkerSettings.max_jobs = ready


async def shutdown(ctx):
    logger.info("Worker shutdown: stopping container pool...")
    await pool.stop()


async def process_submission(ctx, submission_id: int):
    logger.info("Processing submission %d in worker...", submission_id)
    try:
        await judge_submission(submission_id)
        logger.info("Successfully judged submission %d", submission_id)
    except Exception:
        logger.exception("Fatal error judging submission %d", submission_id)
        # V1: persist ERROR status so the submission doesn't remain permanently
        # PENDING. Use a fresh session in case the original one is broken.
        try:
            async with AsyncSessionLocal() as db:
                from models import Submission
                sub = await db.get(Submission, submission_id)
                if sub and sub.status not in ("DONE", "ERROR"):
                    sub.status = "ERROR"
                    await db.commit()
        except Exception:
            logger.exception("Failed to persist ERROR status for submission %d", submission_id)
        raise  # re-raise so ARQ marks the job as failed


class WorkerSettings:
    functions = [process_submission]
    # V2: use from_dsn so credentials, TLS (rediss://), and DB index are preserved.
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    on_startup = startup
    on_shutdown = shutdown
    # V3: overwritten at startup to actual ready container count.
    max_jobs = JUDGE_POOL_SIZE
