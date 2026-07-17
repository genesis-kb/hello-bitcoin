import asyncio
from db import AsyncSessionLocal
from models import Submission
from judge.pool import pool
from judge.runner import run_code
import json

async def debug():
    await pool.start()
    code = """class FieldElement:
    def __init__(self, num, prime):
        self.num = num
        self.prime = prime
    def __add__(self, other):
        return FieldElement((self.num + other.num) % self.prime, self.prime)
"""
    wrapper = """
import sys
_lines = sys.stdin.read().strip().split('\n')
_prime = int(_lines[0])
_a     = int(_lines[1])
_b     = int(_lines[2])
_result = FieldElement(_a, _prime) + FieldElement(_b, _prime)
print(_result.num)
"""
    full = code + "\n" + wrapper
    res = await run_code(pool, "python3", full, "13\n7\n12", 5.0)
    print("Verdict:", res.verdict)
    print("Stdout:", res.stdout)
    print("Stderr:", res.stderr)
    await pool.stop()

asyncio.run(debug())
