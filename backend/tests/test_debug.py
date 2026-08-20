import os
os.environ["SANDBOX_MEMORY_MB"] = "1024"  # rustc needs more than 256MB
os.environ["JUDGE_POOL_LABEL"] = "test-runner"

import asyncio
import pytest
from judge.pool import pool
from judge.runner import run_code

@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for the module."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module", autouse=True)
async def judge_pool(event_loop):
    await pool.start()
    yield pool
    await pool.stop()

# Helper codes for AC (sum two integers)
PY_AC = "import sys\nprint(sum(map(int, sys.stdin.read().split())))"
JS_AC = """const fs = require('fs');
const input = fs.readFileSync('/dev/stdin', 'utf-8').trim().split(/\\s+/);
console.log(parseInt(input[0]) + parseInt(input[1]));
"""
RUST_AC = """use std::io::{self, Read};
fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let sum: i32 = input.split_whitespace().map(|x| x.parse::<i32>().unwrap()).sum();
    println!("{}", sum);
}
"""

@pytest.mark.asyncio
@pytest.mark.parametrize("language,source,stdin,expected_output,expected_verdict", [
    # python3
    ("python3", PY_AC, "1 2\n", "3\n", "AC"),
    ("python3", "while True: pass", "1 2\n", "", "TLE"),
    ("python3", "1/0", "1 2\n", "", "RE"),
    ("python3", "def syntax error:", "1 2\n", "", "CE"),
    
    # javascript
    ("javascript", JS_AC, "1 2\n", "3\n", "AC"),
    ("javascript", "while(true) {}", "1 2\n", "", "TLE"),
    ("javascript", "throw new Error('RE');", "1 2\n", "", "RE"),
    ("javascript", "this is not js", "1 2\n", "", "CE"),
    
    # rust
    ("rust", RUST_AC, "1 2\n", "3\n", "AC"),
    ("rust", "fn main() { loop {} }", "1 2\n", "", "TLE"),
    ("rust", "fn main() { panic!(\"RE\"); }", "1 2\n", "", "RE"),
    ("rust", "fn main() { syntax error }", "1 2\n", "", "CE"),
])
async def test_run_code(language, source, stdin, expected_output, expected_verdict):
    res = await run_code(
        pool=pool,
        language=language,
        source=source,
        stdin=stdin,
        time_limit=1.0,
        memory_limit=1024,
        expected_output=expected_output
    )
    
    if res.verdict != expected_verdict:
        pytest.fail(f"Expected {expected_verdict}, got {res.verdict}. stdout: {res.stdout}, stderr: {res.stderr}")
