import asyncio
import aiohttp
import random
import time
import uuid

# Configuration
API_BASE = "http://localhost:8001/api"
TOTAL_SUBMISSIONS = 10000
CONCURRENCY = 100  # Number of concurrent requests

PROBLEMS = ["ch01_field_add", "ch01_field_mul", "ch02_point_add"]
# Python codes that will yield different verdicts for problem ch01_field_add
STARTER_CODE = """class FieldElement:
    def __init__(self, num, prime):
        if num >= prime or num < 0:
            raise ValueError(f'Num {num} not in field range 0 to {prime - 1}')
        self.num = num
        self.prime = prime

    def __repr__(self):
        return f'FieldElement_{self.prime}({self.num})'

    def __eq__(self, other):
        if other is None:
            return False
        return self.num == other.num and self.prime == other.prime
"""

SOURCE_CODES = {
    "python3": {
        "AC": STARTER_CODE + """
    def __add__(self, other):
        if self.prime != other.prime:
            raise TypeError('Cannot add two numbers in different Fields')
        return FieldElement((self.num + other.num) % self.prime, self.prime)
""",
        "WA": STARTER_CODE + """
    def __add__(self, other):
        if self.prime != other.prime:
            raise TypeError('Cannot add two numbers in different Fields')
        return FieldElement((self.num + other.num + 1) % self.prime, self.prime)
""",
        "TLE": STARTER_CODE + """
    def __add__(self, other):
        while True: pass
""",
        "RE": STARTER_CODE + """
    def __add__(self, other):
        return 1/0
"""
    },
    "node": {
        "AC": """class FieldElement {
    constructor(num, prime) {
        if (num >= prime || num < 0) throw new Error("Invalid");
        this.num = num; this.prime = prime;
    }
    add(other) {
        if (this.prime !== other.prime) throw new Error("Invalid");
        return new FieldElement((this.num + other.num) % this.prime, this.prime);
    }
}
""",
        "WA": """class FieldElement {
    constructor(num, prime) { this.num = num; this.prime = prime; }
    add(other) { return new FieldElement((this.num + other.num + 1) % this.prime, this.prime); }
}
""",
        "TLE": """class FieldElement {
    constructor(num, prime) { this.num = num; this.prime = prime; }
    add(other) { while(true) {} }
}
""",
        "RE": """class FieldElement {
    constructor(num, prime) { this.num = num; this.prime = prime; }
    add(other) { throw new Error("RE"); }
}
"""
    },
    "rust": {
        "AC": """#[derive(Debug, PartialEq, Clone)]
pub struct FieldElement { pub num: u64, pub prime: u64 }
impl FieldElement {
    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }
    pub fn add(&self, other: &Self) -> Self { Self { num: (self.num + other.num) % self.prime, prime: self.prime } }
}
""",
        "WA": """#[derive(Debug, PartialEq, Clone)]
pub struct FieldElement { pub num: u64, pub prime: u64 }
impl FieldElement {
    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }
    pub fn add(&self, other: &Self) -> Self { Self { num: (self.num + other.num + 1) % self.prime, prime: self.prime } }
}
""",
        "TLE": """#[derive(Debug, PartialEq, Clone)]
pub struct FieldElement { pub num: u64, pub prime: u64 }
impl FieldElement {
    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }
    pub fn add(&self, other: &Self) -> Self { loop {} }
}
""",
        "RE": """#[derive(Debug, PartialEq, Clone)]
pub struct FieldElement { pub num: u64, pub prime: u64 }
impl FieldElement {
    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }
    pub fn add(&self, other: &Self) -> Self { panic!("RE"); }
}
"""
    }
}
VERDICTS = ["AC", "WA", "TLE", "RE"]
LANGUAGES = ["python3", "node", "rust"]

async def register_user(session, i):
    username = f"stress_user_{i}_{uuid.uuid4().hex[:8]}"
    email = f"{username}@example.com"
    password = "password123"
    
    async with session.post(f"{API_BASE}/auth/register", json={
        "username": username,
        "email": email,
        "password": password
    }) as resp:
        if resp.status == 201:
            data = await resp.json()
            return data["access_token"]
        else:
            return None

async def submit_code(session, token, sem, stats):
    async with sem:
        problem = "ch01_field_add"  # Always test this one for consistent verdicts
        verdict = random.choice(VERDICTS)
        lang = random.choice(LANGUAGES)
        
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "problem_id": problem,
            "language": lang,
            "source": SOURCE_CODES[lang][verdict]
        }
        
        start_time = time.time()
        try:
            async with session.post(f"{API_BASE}/submissions", json=payload, headers=headers) as resp:
                if resp.status == 201:
                    stats["success"] += 1
                else:
                    stats["failed"] += 1
        except Exception:
            stats["failed"] += 1
            
        stats["latencies"].append(time.time() - start_time)

async def main():
    print(f"Starting stress test for {TOTAL_SUBMISSIONS} submissions with concurrency {CONCURRENCY}...")
    
    # We will reuse a smaller pool of users to avoid registering 10k users which is slow
    NUM_USERS = 50
    print(f"Registering {NUM_USERS} test users...")
    
    tokens = []
    async with aiohttp.ClientSession() as session:
        for i in range(NUM_USERS):
            token = await register_user(session, i)
            if token:
                tokens.append(token)
                
        if not tokens:
            print("Failed to register users. Is the server running?")
            return
            
        print(f"Registered {len(tokens)} users successfully. Starting submission flood...")
        
        sem = asyncio.Semaphore(CONCURRENCY)
        stats = {"success": 0, "failed": 0, "latencies": []}
        
        start_time = time.time()
        
        tasks = []
        for _ in range(TOTAL_SUBMISSIONS):
            token = random.choice(tokens)
            tasks.append(asyncio.create_task(submit_code(session, token, sem, stats)))
            
        # Optional: Print progress every second
        async def print_progress():
            while len(stats["latencies"]) < TOTAL_SUBMISSIONS:
                print(f"Progress: {len(stats['latencies'])} / {TOTAL_SUBMISSIONS} requests completed")
                await asyncio.sleep(1)
                
        progress_task = asyncio.create_task(print_progress())
        await asyncio.gather(*tasks)
        progress_task.cancel()
        
        end_time = time.time()
        
        total_time = end_time - start_time
        avg_latency = sum(stats["latencies"]) / len(stats["latencies"])
        req_per_sec = TOTAL_SUBMISSIONS / total_time
        
        print("\n--- Stress Test Results ---")
        print(f"Total Submissions: {TOTAL_SUBMISSIONS}")
        print(f"Successful HTTP Requests: {stats['success']}")
        print(f"Failed HTTP Requests: {stats['failed']}")
        print(f"Total Time: {total_time:.2f} seconds")
        print(f"Requests Per Second: {req_per_sec:.2f} req/s")
        print(f"Average Request Latency: {avg_latency:.4f} seconds")
        print("---------------------------")
        print("NOTE: This measures HTTP submission acceptance rate.")
        print("The actual judging occurs asynchronously in the background.")
        print("Monitor the server logs to see the judging throughput!")

if __name__ == "__main__":
    asyncio.run(main())
