"""ARQ worker — processes judging jobs from the Redis queue."""

import logging
from urllib.parse import urlparse

from arq.connections import RedisSettings

from config import JUDGE_POOL_SIZE, REDIS_URL
from judge.pool import pool
from services.judging import judge_submission

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


async def startup(ctx):
    logger.info("Worker startup: starting container pool...")
    await pool.start()
    ctx["pool"] = pool


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


_parsed_url = urlparse(REDIS_URL)


class WorkerSettings:
    functions = [process_submission]
    redis_settings = RedisSettings(
        host=_parsed_url.hostname or "localhost",
        port=_parsed_url.port or 6379,
        database=int(_parsed_url.path.lstrip("/")) if _parsed_url.path.lstrip("/") else 0,
    )
    on_startup = startup
    on_shutdown = shutdown
    # Pull no more jobs than the pool can handle concurrently.
    # This prevents coroutines from stacking up on pool.acquire() with a 3-hour timeout.
    max_jobs = JUDGE_POOL_SIZE
