"""
Stress test — runs as pytest.

Usage:
    # Normal run (2500 submissions, 100 concurrent):
    pytest tests/stress_test.py -v -s

    # Override submission count:
    STRESS_TOTAL=500 pytest tests/stress_test.py -v -s
"""
import asyncio
import os
import time
import uuid
import random
import aiohttp
import pytest

# ── Configuration ─────────────────────────────────────────────────────────────

API_BASE       = os.environ.get("API_BASE", "http://localhost:8001/api")
TOTAL          = int(os.environ.get("STRESS_TOTAL", "2500"))
CONCURRENCY    = int(os.environ.get("STRESS_CONCURRENCY", "100"))
NUM_USERS      = int(os.environ.get("STRESS_USERS", "50"))

VERDICTS  = ["AC", "WA", "TLE", "RE"]
LANGUAGES = ["python3", "javascript", "rust"]

# ── Source codes ──────────────────────────────────────────────────────────────

_PY_BASE = """\
class FieldElement:
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
        "AC":  _PY_BASE + "    def __add__(self, other):\n        if self.prime != other.prime:\n            raise TypeError('Cannot add two numbers in different Fields')\n        return FieldElement((self.num + other.num) % self.prime, self.prime)\n",
        "WA":  _PY_BASE + "    def __add__(self, other):\n        if self.prime != other.prime:\n            raise TypeError('Cannot add two numbers in different Fields')\n        return FieldElement((self.num + other.num + 1) % self.prime, self.prime)\n",
        "TLE": _PY_BASE + "    def __add__(self, other):\n        while True: pass\n",
        "RE":  _PY_BASE + "    def __add__(self, other):\n        return 1/0\n",
    },
    "javascript": {
        "AC":  'class FieldElement {\n  constructor(num, prime) { if (num >= prime || num < 0) throw new Error("Invalid"); this.num = num; this.prime = prime; }\n  add(other) { if (this.prime !== other.prime) throw new Error("Invalid"); return new FieldElement((this.num + other.num) % this.prime, this.prime); }\n}\n',
        "WA":  'class FieldElement {\n  constructor(num, prime) { this.num = num; this.prime = prime; }\n  add(other) { return new FieldElement((this.num + other.num + 1) % this.prime, this.prime); }\n}\n',
        "TLE": 'class FieldElement {\n  constructor(num, prime) { this.num = num; this.prime = prime; }\n  add(other) { while(true) {} }\n}\n',
        "RE":  'class FieldElement {\n  constructor(num, prime) { this.num = num; this.prime = prime; }\n  add(other) { throw new Error("RE"); }\n}\n',
    },
    "rust": {
        "AC":  '#[derive(Debug, PartialEq, Clone)]\npub struct FieldElement { pub num: u64, pub prime: u64 }\nimpl FieldElement {\n    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }\n    pub fn add(&self, other: &Self) -> Self { Self { num: (self.num + other.num) % self.prime, prime: self.prime } }\n}\n',
        "WA":  '#[derive(Debug, PartialEq, Clone)]\npub struct FieldElement { pub num: u64, pub prime: u64 }\nimpl FieldElement {\n    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }\n    pub fn add(&self, other: &Self) -> Self { Self { num: (self.num + other.num + 1) % self.prime, prime: self.prime } }\n}\n',
        "TLE": '#[derive(Debug, PartialEq, Clone)]\npub struct FieldElement { pub num: u64, pub prime: u64 }\nimpl FieldElement {\n    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }\n    pub fn add(&self, other: &Self) -> Self { loop {} }\n}\n',
        "RE":  '#[derive(Debug, PartialEq, Clone)]\npub struct FieldElement { pub num: u64, pub prime: u64 }\nimpl FieldElement {\n    pub fn new(num: u64, prime: u64) -> Self { Self { num, prime } }\n    pub fn add(&self, other: &Self) -> Self { panic!("RE"); }\n}\n',
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register_user(session: aiohttp.ClientSession, idx: int):
    name = f"stress_{idx}_{uuid.uuid4().hex[:6]}"
    async with session.post(f"{API_BASE}/auth/register", json={
        "username": name, "email": f"{name}@example.com", "password": "password123"
    }) as r:
        if r.status == 201:
            return (await r.json())["access_token"]
    return None


async def _admin_token(session: aiohttp.ClientSession):
    async with session.post(f"{API_BASE}/auth/login", json={
        "email": "admin@example.com", "password": "admin1234"
    }) as r:
        if r.status == 200:
            return (await r.json())["access_token"]
    return None


async def _submit(session, token, sem, stats, lang, verdict):
    async with sem:
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"problem_id": "ch01_field_add", "language": lang, "source": SOURCE_CODES[lang][verdict]}
        t0 = time.perf_counter()
        try:
            async with session.post(f"{API_BASE}/submissions", json=payload, headers=headers) as r:
                ok = r.status == 201
        except Exception:
            ok = False
        elapsed = time.perf_counter() - t0

        if ok:
            stats["success"] += 1
            stats["by_lang"][lang]["success"] += 1
        else:
            stats["failed"] += 1
            stats["by_lang"][lang]["failed"] += 1
        stats["latencies"].append(elapsed)
        stats["by_lang"][lang]["latencies"].append(elapsed)
        stats["by_verdict"][verdict] += 1


def _pct(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]


def _ms(s):
    return f"{s * 1000:.1f}ms"


def _print_final_report(stats, total_time, judging_time, judging_rate):
    all_lat  = stats["latencies"]
    avg_lat  = sum(all_lat) / len(all_lat) if all_lat else 0
    p50      = _pct(all_lat, 50)
    p95      = _pct(all_lat, 95)
    p99      = _pct(all_lat, 99)
    req_s    = TOTAL / total_time if total_time else 0
    est_min  = (100_000 / judging_rate / 60) if judging_rate else float("inf")

    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich import box

        console = Console()

        overview = (
            f"[bold]Total Submissions:[/]   {TOTAL}\n"
            f"[bold]Success / Failed:[/]    [green]{stats['success']}[/] / [red]{stats['failed']}[/]\n"
            f"[bold]HTTP Phase Time:[/]     {total_time:.2f}s  ([cyan]{req_s:.1f} req/s[/])\n"
            f"[bold]Avg Latency:[/]         {_ms(avg_lat)}\n"
            f"[bold]Latency p50/p95/p99:[/] {_ms(p50)} / [yellow]{_ms(p95)}[/] / [red]{_ms(p99)}[/]"
        )
        console.print(Panel(overview, title="[bold cyan]📊 HTTP Phase[/]", box=box.ROUNDED, expand=False))

        judging_panel = (
            f"[bold]Judging Time:[/]   {judging_time:.2f}s\n"
            f"[bold]Throughput:[/]     [cyan]{judging_rate:.2f} verdicts/sec[/]\n"
            f"[bold]Est. for 100k:[/]  [yellow]{est_min:.1f} minutes[/]"
        )
        console.print(Panel(judging_panel, title="[bold magenta]⚡ Judging Performance[/]", box=box.ROUNDED, expand=False))

        lang_t = Table(title="Per-Language Breakdown", box=box.SIMPLE_HEAVY, show_lines=True)
        for col, style, just in [
            ("Language", "bold", "left"), ("Submitted", "", "right"),
            ("Success", "green", "right"), ("Failed", "red", "right"),
            ("p50", "", "right"), ("p95", "yellow", "right"), ("p99", "red", "right"),
        ]:
            lang_t.add_column(col, style=style, justify=just)

        for lang in LANGUAGES:
            ls = stats["by_lang"][lang]
            n  = ls["success"] + ls["failed"]
            lats = ls["latencies"]
            lang_t.add_row(
                lang, str(n), str(ls["success"]), str(ls["failed"]),
                _ms(_pct(lats, 50)), _ms(_pct(lats, 95)), _ms(_pct(lats, 99)),
            )
        console.print(lang_t)

        v_t = Table(title="Verdict Distribution (intended)", box=box.SIMPLE_HEAVY)
        v_t.add_column("Verdict", style="bold")
        v_t.add_column("Count", justify="right")
        for v in VERDICTS:
            v_t.add_row(v, str(stats["by_verdict"][v]))
        console.print(v_t)

    except ImportError:
        print("\n" + "=" * 60)
        print("  STRESS TEST RESULTS")
        print("=" * 60)
        print(f"  Submissions      : {TOTAL}")
        print(f"  Success / Failed : {stats['success']} / {stats['failed']}")
        print(f"  HTTP time        : {total_time:.2f}s ({req_s:.1f} req/s)")
        print(f"  p50 / p95 / p99  : {_ms(p50)} / {_ms(p95)} / {_ms(p99)}")
        print(f"  Judging time     : {judging_time:.2f}s ({judging_rate:.2f} verdicts/s)")
        print(f"  Est. 100k        : {est_min:.1f} min")
        print("-" * 60)
        for lang in LANGUAGES:
            ls = stats["by_lang"][lang]
            n  = ls["success"] + ls["failed"]
            lats = ls["latencies"]
            print(f"  {lang:<12} {n:>6} | ok={ls['success']} | {_ms(_pct(lats,50))} / {_ms(_pct(lats,95))} / {_ms(_pct(lats,99))}")
        print("=" * 60)


# ── Pytest test ───────────────────────────────────────────────────────────────

@pytest.mark.stress
@pytest.mark.asyncio
async def test_stress():
    """
    Full load test: register users, flood submissions, wait for judging to drain.
    Run with:  pytest tests/stress_test.py -v -s
    """
    try:
        from rich.console import Console
        from rich.progress import (
            Progress, SpinnerColumn, BarColumn,
            TaskProgressColumn, TimeElapsedColumn, TextColumn,
        )
        from rich.live import Live
        from rich.table import Table
        from rich.panel import Panel
        from rich import box
        _rich = True
        console = Console()
    except ImportError:
        _rich = False
        console = None

    # ── Phase 1: register users ─────────────────────────────────────────────
    print(f"\nRegistering {NUM_USERS} stress users…")
    tokens = []
    async with aiohttp.ClientSession() as session:
        for i in range(NUM_USERS):
            t = await _register_user(session, i)
            if t:
                tokens.append(t)

    assert tokens, "Failed to register any users — is the server running?"

    async with aiohttp.ClientSession() as session:
        admin_tok = await _admin_token(session)
    assert admin_tok, "Failed to get admin token — did you seed the DB?"

    print(f"✓ {len(tokens)} users ready. Flooding {TOTAL} submissions (concurrency={CONCURRENCY})…\n")

    # ── Phase 2: submission flood ───────────────────────────────────────────
    sem   = asyncio.Semaphore(CONCURRENCY)
    stats = {
        "success": 0, "failed": 0, "latencies": [],
        "by_lang":    {lang: {"success": 0, "failed": 0, "latencies": []} for lang in LANGUAGES},
        "by_verdict": {v: 0 for v in VERDICTS},
    }

    all_combos  = [(lang, v) for lang in LANGUAGES for v in VERDICTS]
    assignments = (all_combos * (TOTAL // len(all_combos) + 1))[:TOTAL]
    random.shuffle(assignments)

    http_start = time.perf_counter()

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(
                _submit(session, random.choice(tokens), sem, stats, lang, verdict)
            )
            for lang, verdict in assignments
        ]

        if _rich:
            done_event = asyncio.Event()
            last_n, last_t = 0, http_start

            async def _rps_watcher():
                nonlocal last_n, last_t

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TextColumn("[cyan]{task.fields[rps]} req/s"),
                console=console, transient=True,
            ) as prog:
                tid = prog.add_task("Submitting", total=TOTAL, rps="—")

                async def _watch():
                    nonlocal last_n, last_t
                    while not done_event.is_set():
                        await asyncio.sleep(0.5)
                        n   = len(stats["latencies"])
                        now = time.perf_counter()
                        rps = (n - last_n) / max(now - last_t, 1e-9)
                        last_n, last_t = n, now
                        prog.update(tid, completed=n, rps=f"{rps:.0f}")

                watcher = asyncio.create_task(_watch())
                await asyncio.gather(*tasks)
                done_event.set()
                await watcher
                prog.update(tid, completed=TOTAL)
        else:
            async def _plain():
                while len(stats["latencies"]) < TOTAL:
                    print(f"  {len(stats['latencies'])}/{TOTAL} submitted…")
                    await asyncio.sleep(2)
            pt = asyncio.create_task(_plain())
            await asyncio.gather(*tasks)
            pt.cancel()

    http_time = time.perf_counter() - http_start
    print(f"\n✓ All {TOTAL} submissions sent in {http_time:.2f}s ({TOTAL/http_time:.1f} req/s)")

    # ── Phase 3: drain judging queue ────────────────────────────────────────
    print("⏳ Waiting for judging queue to drain…\n")
    judging_start = time.perf_counter()
    judging_rate  = 0.0

    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {admin_tok}"}

        # Baseline (submissions that existed before this run)
        async with session.get(f"{API_BASE}/admin/stats", headers=headers) as r:
            base = await r.json() if r.status == 200 else {}
        verd0    = base.get("verdicts", {})
        base_done = base.get("submissions_total", 0) - verd0.get("PENDING", 0) - verd0.get("JUDGING", 0)

        # To prevent waiting forever for stale/stuck jobs:
        stuck_timeout = 60
        last_done = base_done
        last_change_time = judging_start

        if _rich:
            def _live_panel(done, pend, elap, rate, eta):
                t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                t.add_column(style="bold")
                t.add_column(justify="right")
                t.add_row("Judged",  f"[green]{done}[/] / {TOTAL}")
                t.add_row("Queue",   f"[yellow]{pend}[/]")
                t.add_row("Elapsed", f"{elap:.0f}s")
                t.add_row("Rate",    f"[cyan]{rate:.1f} v/s[/]")
                t.add_row("ETA",     f"[magenta]~{eta:.0f}s[/]" if rate > 0 else "—")
                return Panel(t, title="[bold magenta]⚡ Judging[/]", expand=False)

            with Live(console=console, refresh_per_second=2) as live:
                while True:
                    async with session.get(f"{API_BASE}/admin/stats", headers=headers) as r:
                        if r.status != 200:
                            await asyncio.sleep(2)
                            continue
                        d    = await r.json()
                        verd = d.get("verdicts", {})
                        pend = verd.get("PENDING", 0) + verd.get("JUDGING", 0)
                        done = d.get("submissions_total", 0) - pend - base_done
                        elap = time.perf_counter() - judging_start
                        rate = done / elap if elap > 0 else 0
                        eta  = pend / rate if rate > 0 else 0
                        judging_rate = rate
                        
                        live.update(_live_panel(done, pend, elap, rate, eta))
                        
                        if pend == 0 or done >= TOTAL:
                            break
                        
                        if done != last_done:
                            last_done = done
                            last_change_time = time.perf_counter()
                        elif time.perf_counter() - last_change_time > stuck_timeout:
                            # Break if queue is stuck
                            break
                            
                    await asyncio.sleep(2)
        else:
            while True:
                async with session.get(f"{API_BASE}/admin/stats", headers=headers) as r:
                    if r.status != 200:
                        await asyncio.sleep(2)
                        continue
                    d    = await r.json()
                    verd = d.get("verdicts", {})
                    pend = verd.get("PENDING", 0) + verd.get("JUDGING", 0)
                    done = d.get("submissions_total", 0) - pend - base_done
                    elap = time.perf_counter() - judging_start
                    rate = done / elap if elap > 0 else 0
                    judging_rate = rate
                    print(f"  [Judging] {done} done | {pend} pending | {rate:.1f} v/s")
                    
                    if pend == 0 or done >= TOTAL:
                        break

                    if done != last_done:
                        last_done = done
                        last_change_time = time.perf_counter()
                    elif time.perf_counter() - last_change_time > stuck_timeout:
                        print(f"  [WARNING] Queue appears stuck for {stuck_timeout}s. Aborting wait.")
                        break

                await asyncio.sleep(2)

    judging_time = time.perf_counter() - judging_start

    # ── Phase 4: final report ───────────────────────────────────────────────
    _print_final_report(stats, http_time, judging_time, judging_rate)

    # ── Pass/fail assertion ─────────────────────────────────────────────────
    rate = stats["success"] / TOTAL
    assert rate >= 0.99, (
        f"HTTP success rate too low: {rate:.1%} ({stats['success']}/{TOTAL} accepted)"
    )


# ── Backwards-compat standalone entry ────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(test_stress())
