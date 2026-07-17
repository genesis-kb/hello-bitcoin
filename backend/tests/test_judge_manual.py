import asyncio
from db import AsyncSessionLocal
from models import Submission
from routes.submissions import judge_submission
from judge.pool import pool

async def run():
    await pool.start()
    try:
        # Get the highest ID submission (which likely failed)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            result = await db.execute(select(Submission).order_by(Submission.id.desc()).limit(1))
            sub = result.scalar_one_or_none()
            sub_id = sub.id if sub else 3
            print(f"Judging submission {sub_id}...")
        await judge_submission(sub_id)
        print("Success")
    except Exception as e:
        import traceback
        traceback.print_exc()
    finally:
        await pool.stop()

asyncio.run(run())
