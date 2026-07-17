import asyncio
from db import AsyncSessionLocal
from routes.submissions import judge_submission
from judge.pool import pool

async def run():
    await pool.start()
    await judge_submission(3)
    await pool.stop()

asyncio.run(run())
