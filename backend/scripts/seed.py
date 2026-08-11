"""
Seed the database with:
  - An admin user (email from ADMIN_EMAIL env var)
  - 3 Programming Bitcoin problems with test cases

Run with:
    cd backend && python scripts/seed.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure the backend/ directory is on the path regardless of where this is run from.
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ADMIN_EMAIL
from db import AsyncSessionLocal, init_db
from models import Problem, TestCase, User, Book, BookChapter, Conference
from auth import hash_password
from sqlalchemy import select

# ─── Problem definitions ──────────────────────────────────────────────────────

PROBLEMS = [
    {
        "id": "ch01_field_add",
        "title": "Finite Field: Addition",
        "chapter": 1,
        "description": "## Finite Field Addition\n\nIn *Programming Bitcoin* Chapter 1, you learn about **Finite Fields** — sets of integers\nmodulo a prime number `p`.\n\nA `FieldElement` represents the number `num` in the field `F_prime`.\n\nYour task is to implement the `add` method on `FieldElement`:\n\n```\nFieldElement(a, prime) + FieldElement(b, prime) = FieldElement((a + b) % prime, prime)\n```\n\n### Rules\n- Both elements must belong to the same field (same `prime`), or raise `TypeError`.\n- The result must stay within `[0, prime)` — use the modulo operator.\n\n### Starter code\nFill in the `pass` inside `add`. Do **not** change anything else.\n\n### Input format (read by the judge harness — you don't need to parse this)\n```\nprime\na\nb\n```\n\n### Output\n```\n(a + b) % prime\n```\n",
        "starter_code": {
            "python3": "class FieldElement:\n    def __init__(self, num, prime):\n        if num >= prime or num < 0:\n            raise ValueError(f'Num {num} not in field range 0 to {prime - 1}')\n        self.num = num\n        self.prime = prime\n\n    def __repr__(self):\n        return f'FieldElement_{self.prime}({self.num})'\n\n    def __eq__(self, other):\n        if other is None:\n            return False\n        return self.num == other.num and self.prime == other.prime\n\n    def __add__(self, other):\n        if self.prime != other.prime:\n            raise TypeError('Cannot add two numbers in different Fields')\n        # YOUR CODE HERE\n        # Hint: return a new FieldElement using modular arithmetic\n        pass\n",
            "node": "class FieldElement {\n    constructor(num, prime) {\n        if (num >= prime || num < 0) {\n            throw new Error(`Num ${num} not in field range 0 to ${prime - 1}`);\n        }\n        this.num = num;\n        this.prime = prime;\n    }\n\n    add(other) {\n        if (this.prime !== other.prime) {\n            throw new Error('Cannot add two numbers in different Fields');\n        }\n        // YOUR CODE HERE\n    }\n}\n",
            "rust": "#[derive(Debug, PartialEq, Clone)]\npub struct FieldElement {\n    pub num: u64,\n    pub prime: u64,\n}\n\nimpl FieldElement {\n    pub fn new(num: u64, prime: u64) -> Self {\n        if num >= prime {\n            panic!(\"Num {} not in field range 0 to {}\", num, prime - 1);\n        }\n        Self { num, prime }\n    }\n\n    pub fn add(&self, other: &Self) -> Self {\n        if self.prime != other.prime {\n            panic!(\"Cannot add two numbers in different Fields\");\n        }\n        // YOUR CODE HERE\n        Self { num: 0, prime: self.prime }\n    }\n}\n"
        },
        "wrapper_code": {
            "python3": "import sys\n_lines = sys.stdin.read().strip().split('\\n')\n_prime = int(_lines[0])\n_a     = int(_lines[1])\n_b     = int(_lines[2])\n_result = FieldElement(_a, _prime) + FieldElement(_b, _prime)\nprint(_result.num)\n",
            "node": "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf-8').trim().split('\\n');\nif (input.length < 3) process.exit(0);\nconst prime = parseInt(input[0], 10);\nconst a = parseInt(input[1], 10);\nconst b = parseInt(input[2], 10);\nconst result = new FieldElement(a, prime).add(new FieldElement(b, prime));\nconsole.log(result.num);\n",
            "rust": "use std::io::{self, Read};\n\nfn main() {\n    let mut input = String::new();\n    io::stdin().read_to_string(&mut input).unwrap();\n    let mut lines = input.trim().lines();\n    \n    let prime: u64 = lines.next().unwrap().parse().unwrap();\n    let a: u64 = lines.next().unwrap().parse().unwrap();\n    let b: u64 = lines.next().unwrap().parse().unwrap();\n    \n    let fe_a = FieldElement::new(a, prime);\n    let fe_b = FieldElement::new(b, prime);\n    let result = fe_a.add(&fe_b);\n    \n    println!(\"{}\", result.num);\n}\n"
        },
        "checker_code": "",
        "time_limit": 2.0,
        "memory_limit": 256,
        "is_published": True,
        "test_cases": [
            ("13\n7\n12", "6",  True),
            ("31\n2\n15", "17", True),
            ("57\n44\n33", "20", False),
            ("97\n50\n50", "3",  False),
            ("223\n100\n150", "27", False),
        ],
    },
    {
        "id": "ch01_field_mul",
        "title": "Finite Field: Multiplication & Power",
        "chapter": 1,
        "description": "## Finite Field Multiplication and Exponentiation\n\nBuilding on Chapter 1, implement two more operations on `FieldElement`:\n\n### `mul`\n```\nFieldElement(a, p) * FieldElement(b, p) = FieldElement((a * b) % p, p)\n```\n\n### `pow`\n```\nFieldElement(a, p) ** n = FieldElement(pow(a, n, p), p)\n```\n",
        "starter_code": {
            "python3": "class FieldElement:\n    def __init__(self, num, prime):\n        if num >= prime or num < 0:\n            raise ValueError(f'Num {num} not in field range 0 to {prime - 1}')\n        self.num = num\n        self.prime = prime\n\n    def __repr__(self):\n        return f'FieldElement_{self.prime}({self.num})'\n\n    def __eq__(self, other):\n        if other is None:\n            return False\n        return self.num == other.num and self.prime == other.prime\n\n    def __add__(self, other):\n        if self.prime != other.prime:\n            raise TypeError('Cannot add two numbers in different Fields')\n        return FieldElement((self.num + other.num) % self.prime, self.prime)\n\n    def __mul__(self, other):\n        if self.prime != other.prime:\n            raise TypeError('Cannot multiply two numbers in different Fields')\n        # YOUR CODE HERE\n        pass\n\n    def __pow__(self, exponent):\n        # YOUR CODE HERE\n        # Hint: use pow(self.num, n % (self.prime - 1), self.prime)\n        # to handle negative exponents via Fermat's Little Theorem\n        pass\n",
            "node": "class FieldElement {\n    constructor(num, prime) {\n        if (num >= prime || num < 0) {\n            throw new Error(`Num ${num} not in field range 0 to ${prime - 1}`);\n        }\n        this.num = num;\n        this.prime = prime;\n    }\n\n    add(other) {\n        if (this.prime !== other.prime) throw new Error('Cannot add');\n        return new FieldElement((this.num + other.num) % this.prime, this.prime);\n    }\n\n    mul(other) {\n        if (this.prime !== other.prime) throw new Error('Cannot multiply');\n        // YOUR CODE HERE\n    }\n\n    pow(exponent) {\n        // YOUR CODE HERE\n    }\n}\n",
            "rust": "#[derive(Debug, PartialEq, Clone)]\npub struct FieldElement {\n    pub num: u64,\n    pub prime: u64,\n}\n\nimpl FieldElement {\n    pub fn new(num: u64, prime: u64) -> Self {\n        if num >= prime { panic!(\"Error\"); }\n        Self { num, prime }\n    }\n\n    pub fn add(&self, other: &Self) -> Self {\n        if self.prime != other.prime { panic!(\"Error\"); }\n        Self { num: (self.num + other.num) % self.prime, prime: self.prime }\n    }\n\n    pub fn mul(&self, other: &Self) -> Self {\n        // YOUR CODE HERE\n        Self { num: 0, prime: self.prime }\n    }\n\n    pub fn pow(&self, exponent: i64) -> Self {\n        // YOUR CODE HERE\n        Self { num: 0, prime: self.prime }\n    }\n}\n"
        },
        "wrapper_code": {
            "python3": "import sys\n_lines  = sys.stdin.read().strip().split('\\n')\n_prime  = int(_lines[0])\n_a      = int(_lines[1])\n_b      = int(_lines[2])\n_n      = int(_lines[3])\n_fe_a   = FieldElement(_a, _prime)\n_fe_b   = FieldElement(_b, _prime)\nprint((_fe_a * _fe_b).num)\nprint((_fe_a ** _n).num)\n",
            "node": "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf-8').trim().split('\\n');\nif (input.length < 4) process.exit(0);\nconst prime = parseInt(input[0], 10);\nconst a = parseInt(input[1], 10);\nconst b = parseInt(input[2], 10);\nconst n = parseInt(input[3], 10);\nconst fe_a = new FieldElement(a, prime);\nconst fe_b = new FieldElement(b, prime);\nconsole.log(fe_a.mul(fe_b).num);\nconsole.log(fe_a.pow(n).num);\n",
            "rust": "use std::io::{self, Read};\n\nfn main() {\n    let mut input = String::new();\n    io::stdin().read_to_string(&mut input).unwrap();\n    let mut lines = input.trim().lines();\n    \n    let prime: u64 = lines.next().unwrap().parse().unwrap();\n    let a: u64 = lines.next().unwrap().parse().unwrap();\n    let b: u64 = lines.next().unwrap().parse().unwrap();\n    let n: i64 = lines.next().unwrap().parse().unwrap();\n    \n    let fe_a = FieldElement::new(a, prime);\n    let fe_b = FieldElement::new(b, prime);\n    println!(\"{}\", fe_a.mul(&fe_b).num);\n    println!(\"{}\", fe_a.pow(n).num);\n}\n"
        },
        "checker_code": "",
        "time_limit": 2.0,
        "memory_limit": 256,
        "is_published": True,
        "test_cases": [
            ("13\n3\n12\n3",   "10\n1",  True),
            ("31\n5\n6\n2",    "30\n25", True),
            ("17\n7\n4\n3",    "11\n3",  False),
            ("23\n15\n21\n10", "16\n3",  False),
            ("41\n37\n12\n20", "34\n1",  False),
        ],
    },
    {
        "id": "ch02_point_add",
        "title": "Elliptic Curve: Point Addition",
        "chapter": 2,
        "description": "## Elliptic Curve Point Addition\n\nIn Chapter 2, you work with points on an elliptic curve:\n\n```\ny² = x³ + ax + b\n```\n\nImplement the `add` method on `Point`. The identity element (point at infinity)\nis represented as `Point(None, None, a, b)`.\n",
        "starter_code": {
            "python3": "class Point:\n    def __init__(self, x, y, a, b):\n        self.a = a\n        self.b = b\n        self.x = x\n        self.y = y\n        if self.x is None:\n            return  # point at infinity — skip curve check\n        if self.y ** 2 != self.x ** 3 + a * x + b:\n            raise ValueError(f'({x}, {y}) is not on the curve')\n\n    def __eq__(self, other):\n        return (\n            self.x == other.x and self.y == other.y\n            and self.a == other.a and self.b == other.b\n        )\n\n    def __repr__(self):\n        if self.x is None:\n            return 'Point(infinity)'\n        return f'Point({self.x},{self.y})_{self.a}_{self.b}'\n\n    def __add__(self, other):\n        if self.a != other.a or self.b != other.b:\n            raise TypeError('Points are not on the same curve')\n\n        # Case 1 & 2: identity element\n        if self.x is None:\n            return other\n        if other.x is None:\n            return self\n\n        # Case 3: additive inverses → point at infinity\n        # YOUR CODE HERE\n\n        # Case 4: point doubling (P == P)\n        # YOUR CODE HERE\n\n        # Case 5: general addition (P != Q)\n        # YOUR CODE HERE\n\n        pass\n",
            "node": "class Point {\n    constructor(x, y, a, b) {\n        this.a = a;\n        this.b = b;\n        this.x = x;\n        this.y = y;\n        if (this.x === null) return;\n        if (Math.pow(this.y, 2) !== Math.pow(this.x, 3) + a * x + b) {\n            throw new Error(`(${x}, ${y}) is not on the curve`);\n        }\n    }\n\n    add(other) {\n        if (this.a !== other.a || this.b !== other.b) {\n            throw new Error('Points are not on the same curve');\n        }\n        if (this.x === null) return other;\n        if (other.x === null) return this;\n        // YOUR CODE HERE\n    }\n}\n",
            "rust": "#[derive(Debug, PartialEq, Clone)]\npub struct Point {\n    pub x: Option<i64>,\n    pub y: Option<i64>,\n    pub a: i64,\n    pub b: i64,\n}\n\nimpl Point {\n    pub fn new(x: Option<i64>, y: Option<i64>, a: i64, b: i64) -> Self {\n        if let (Some(xv), Some(yv)) = (x, y) {\n            if yv * yv != xv * xv * xv + a * xv + b {\n                panic!(\"Not on curve\");\n            }\n        }\n        Self { x, y, a, b }\n    }\n\n    pub fn add(&self, other: &Self) -> Self {\n        if self.a != other.a || self.b != other.b {\n            panic!(\"Not on same curve\");\n        }\n        if self.x.is_none() { return other.clone(); }\n        if other.x.is_none() { return self.clone(); }\n        // YOUR CODE HERE\n        Self { x: None, y: None, a: self.a, b: self.b }\n    }\n}\n"
        },
        "wrapper_code": {
            "python3": "import sys\n\n_lines = sys.stdin.read().strip().split('\\n')\n_a, _b = map(int, _lines[0].split())\n\ndef _parse(line, a, b):\n    line = line.strip()\n    if line == 'inf':\n        return Point(None, None, a, b)\n    x, y = map(int, line.split())\n    return Point(x, y, a, b)\n\n_p1 = _parse(_lines[1], _a, _b)\n_p2 = _parse(_lines[2], _a, _b)\n_r  = _p1 + _p2\n\nif _r.x is None:\n    print('inf')\nelse:\n    print(f'{int(_r.x)} {int(_r.y)}')\n",
            "node": "const fs = require('fs');\nconst lines = fs.readFileSync(0, 'utf-8').trim().split('\\n');\nif (lines.length < 3) process.exit(0);\nconst [a, b] = lines[0].split(' ').map(Number);\n\nfunction parse(line, a, b) {\n    if (line === 'inf') return new Point(null, null, a, b);\n    const [x, y] = line.split(' ').map(Number);\n    return new Point(x, y, a, b);\n}\n\nconst p1 = parse(lines[1], a, b);\nconst p2 = parse(lines[2], a, b);\nconst r = p1.add(p2);\n\nif (r.x === null) {\n    console.log('inf');\n} else {\n    console.log(`${r.x} ${r.y}`);\n}\n",
            "rust": "use std::io::{self, Read};\n\nfn parse(line: &str, a: i64, b: i64) -> Point {\n    if line == \"inf\" {\n        return Point::new(None, None, a, b);\n    }\n    let parts: Vec<i64> = line.split_whitespace().map(|s| s.parse().unwrap()).collect();\n    Point::new(Some(parts[0]), Some(parts[1]), a, b)\n}\n\nfn main() {\n    let mut input = String::new();\n    io::stdin().read_to_string(&mut input).unwrap();\n    let mut lines = input.trim().lines();\n    \n    let first_line = lines.next().unwrap();\n    let ab: Vec<i64> = first_line.split_whitespace().map(|s| s.parse().unwrap()).collect();\n    let a = ab[0];\n    let b = ab[1];\n    \n    let p1 = parse(lines.next().unwrap(), a, b);\n    let p2 = parse(lines.next().unwrap(), a, b);\n    \n    let r = p1.add(&p2);\n    if r.x.is_none() {\n        println!(\"inf\");\n    } else {\n        println!(\"{} {}\", r.x.unwrap(), r.y.unwrap());\n    }\n}\n"
        },
        "checker_code": "",
        "time_limit": 2.0,
        "memory_limit": 256,
        "is_published": True,
        "test_cases": [
            ("5 7\n2 5\n-1 -1",  "3 -7", True),
            ("5 7\n-1 1\n-1 -1", "inf",  True),
            ("5 7\n-1 -1\n-1 -1", "18 77", False),
            ("5 7\ninf\n2 5",    "2 5",  False),
            ("5 7\n2 5\ninf",    "2 5",  False),
        ],
    },
]


# ─── Seeding logic ────────────────────────────────────────────────────────────

async def seed():
    await init_db()

    async with AsyncSessionLocal() as db:
        # Admin user
        existing = (await db.execute(select(User).where(User.email == ADMIN_EMAIL))).scalar_one_or_none()
        if not existing:
            admin = User(
                username="admin",
                email=ADMIN_EMAIL,
                password_hash=hash_password("admin1234"),
                role="admin",
            )
            db.add(admin)
            await db.commit()
            await db.refresh(admin)
            print(f"✓ Created admin user: {ADMIN_EMAIL} / admin1234")
        else:
            admin = existing
            print(f"  Admin user already exists: {ADMIN_EMAIL}")

        # Books
        book1 = (await db.execute(select(Book).where(Book.slug == "programming-bitcoin"))).scalar_one_or_none()
        if not book1:
            book1 = Book(title="Programming Bitcoin", slug="programming-bitcoin", author="Jimmy Song", is_published=True, description="Learn how to program Bitcoin from scratch.")
            db.add(book1)
            await db.flush()
            pb_chapters = []
            for i in range(1, 15):
                ch = BookChapter(book_id=book1.id, number=i, title=f"Chapter {i}", description=f"Programming Bitcoin Chapter {i}")
                pb_chapters.append(ch)
            db.add_all(pb_chapters)
            await db.flush()
            print(f"✓ Created book '{book1.title}' with {len(pb_chapters)} chapters.")
        else:
            pb_chapters = (await db.execute(select(BookChapter).where(BookChapter.book_id == book1.id).order_by(BookChapter.number))).scalars().all()

        book2 = (await db.execute(select(Book).where(Book.slug == "grokking-bitcoin"))).scalar_one_or_none()
        if not book2:
            book2 = Book(title="Grokking Bitcoin", slug="grokking-bitcoin", author="Kalle Rosenbaum", is_published=True, description="Deep dive into Bitcoin under the hood.")
            db.add(book2)
            await db.flush()
            gb_chapters = []
            for i in range(1, 4):
                ch = BookChapter(book_id=book2.id, number=i, title=f"Chapter {i}", description=f"Grokking Bitcoin Chapter {i}")
                gb_chapters.append(ch)
            db.add_all(gb_chapters)
            await db.flush()
            print(f"✓ Created book '{book2.title}' with {len(gb_chapters)} chapters.")
        else:
            gb_chapters = (await db.execute(select(BookChapter).where(BookChapter.book_id == book2.id).order_by(BookChapter.number))).scalars().all()

        # Conferences
        conf1 = (await db.execute(select(Conference).where(Conference.slug == "advancing-bitcoin-2024"))).scalar_one_or_none()
        if not conf1:
            conf1 = Conference(name="Advancing Bitcoin 2024", slug="advancing-bitcoin-2024", year=2024, is_published=True, description="Advancing Bitcoin 2024 problems")
            db.add(conf1)
            await db.flush()
            print(f"✓ Created conference '{conf1.name}'.")

        conf2 = (await db.execute(select(Conference).where(Conference.slug == "bitcoin-2023"))).scalar_one_or_none()
        if not conf2:
            conf2 = Conference(name="Bitcoin 2023", slug="bitcoin-2023", year=2023, is_published=True, description="Bitcoin 2023 problems")
            db.add(conf2)
            await db.flush()
            print(f"✓ Created conference '{conf2.name}'.")

        # Problems + test cases for Programming Bitcoin
        for p_data in PROBLEMS:
            existing_problem = await db.get(Problem, p_data["id"])
            if existing_problem:
                print(f"  Problem '{p_data['id']}' already exists — skipping.")
                continue

            test_cases_data = p_data.pop("test_cases")
            chapter_num = p_data.pop("chapter", 1)
            
            problem = Problem(
                **p_data,
                source_type="book",
                book_chapter_id=pb_chapters[chapter_num - 1].id,
                created_by=admin.id
            )
            db.add(problem)
            await db.flush()

            for i, (inp, expected, is_sample) in enumerate(test_cases_data):
                tc = TestCase(
                    problem_id=problem.id,
                    input=inp,
                    expected_output=expected,
                    is_sample=is_sample,
                    points=1,
                    order_index=i,
                )
                db.add(tc)

            print(f"✓ Created problem '{problem.id}' with {len(test_cases_data)} test cases.")
            
        # Conference 1 Mock problems (6 problems)
        for i in range(6):
            pid = f"adv-btc-2024-prob-{i+1}"
            if not await db.get(Problem, pid):
                db.add(Problem(
                    id=pid, title=f"Advancing Bitcoin 2024 Problem {i+1}", source_type="conference",
                    conference_id=conf1.id, order_index=i, description="Mock problem.",
                    starter_code={"python3": "def solve():\\n    pass"}, wrapper_code={"python3": "print('ok')"},
                    checker_code="", time_limit=2.0, memory_limit=256, is_published=True, created_by=admin.id
                ))
                print(f"✓ Created mock problem '{pid}' for {conf1.name}.")
        
        # Conference 2 Mock problems (3 problems)
        for i in range(3):
            pid = f"btc-2023-prob-{i+1}"
            if not await db.get(Problem, pid):
                db.add(Problem(
                    id=pid, title=f"Bitcoin 2023 Problem {i+1}", source_type="conference",
                    conference_id=conf2.id, order_index=i, description="Mock problem.",
                    starter_code={"python3": "def solve():\\n    pass"}, wrapper_code={"python3": "print('ok')"},
                    checker_code="", time_limit=2.0, memory_limit=256, is_published=True, created_by=admin.id
                ))
                print(f"✓ Created mock problem '{pid}' for {conf2.name}.")
                
        # Grokking Bitcoin Mock problems (3 problems in Ch 1)
        if book2 and gb_chapters:
            gb_ch1 = gb_chapters[0]
            for i in range(3):
                pid = f"gb-ch1-prob-{i+1}"
                if not (await db.get(Problem, pid)):
                    db.add(Problem(
                        id=pid, title=f"Grokking Ch1 Problem {i+1}", source_type="book", book_chapter_id=gb_ch1.id,
                        order_index=i, description=f"Mock problem {i+1} for Grokking Bitcoin Chapter 1.",
                        starter_code={"python3": "def solve():\n    pass"}, wrapper_code={"python3": "print('ok')"},
                        checker_code="", time_limit=2.0, memory_limit=256, is_published=True, created_by=admin.id
                    ))
                    print(f"✓ Created mock problem '{pid}' for {book2.title} Ch 1.")

        await db.commit()

    print("\nSeed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
