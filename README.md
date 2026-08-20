# Programming Bitcoin Online Judge (Hello Bitcoin)

Welcome to Hello Bitcoin! This platform is designed to help you practice and verify your solutions to the cryptography exercises presented in *Programming Bitcoin* by Jimmy Song.

## Overview
- **Solve problems**: Write your solutions directly in the browser using the interactive CodeMirror editor.
- **Instant feedback**: Your code is executed in isolated, pre-warmed Docker containers against hidden test cases.
- **Multiple languages**: Supports Python 3 (primary), JavaScript, and Rust.
- **Admin Panel**: For instructors or administrators to manage problems, test cases, books, conferences, and users.

## How to Use the Platform

### 1. Registration & Login
Navigate to the top right and click **Login**. You can either log in to an existing account or switch to the **Register** tab to create a new one. Once authenticated, your submissions will be tracked.

### 2. Exploring Problems
The homepage lists all published problems, categorized by book chapter or conference. Click on a problem to open its workspace.

### 3. Solving a Problem
When you open a problem, you'll see a split layout:
- **Left Panel**: Contains the problem description, rules, and sample test cases.
- **Right Panel**: Contains the code editor. It is pre-filled with starter code. Do not change the class/function signatures provided in the starter code, as the judging harness relies on them.

**To Submit:**
1. Choose your language from the dropdown.
2. Fill in your solution (e.g., implementing the `__add__` method).
3. Click the **Submit** button.
4. Your code is evaluated in real-time via Server-Sent Events (SSE), and you'll see a verdict (`AC`, `WA`, `CE`, `TLE`, `RE`).

### 4. Verdicts Explained
- **AC (Accepted)**: Your solution passed all test cases!
- **WA (Wrong Answer)**: Your output didn't match the expected output.
- **TLE (Time Limit Exceeded)**: Your code ran too long. Check for infinite loops or inefficient algorithms.
- **RE (Runtime Error)**: Your code crashed or raised an unhandled exception during execution.
- **CE (Compile/Syntax Error)**: Your code failed to compile (or had a syntax error in Python/JS).

### 5. Viewing Submissions
Click on **My Submissions** to see a history of all your attempts. You can click on the problem ID in the table to return to the problem workspace.

## For Administrators

If your account has the `admin` role, you'll see an **⚙ Admin** link in the navigation bar.

### Admin Dashboard
The dashboard provides a high-level view of platform statistics (total users, submissions, verdicts) and lists all problems.

### Problem Management (Polygon Style)
Click **+ New Problem** or **Edit** on an existing problem to open the problem editor:
- **General Tab**: Set the ID, title, parent source (Book Chapter or Conference), time/memory limits, and write the description using Markdown.
- **Code Editors Tab**: Define the starter code (shown to users), the wrapper/harness code (appended to user submissions), and a custom checker (if the default exact-match checker is insufficient).
- **Test Cases Tab**: Create, edit, and categorize test cases. Mark cases as "Sample" if they should be visible to users in the problem description.

### User Management
The **Users** page allows you to view all registered users and promote/demote them to/from the admin role.

## Local Development Setup

To run the platform locally, follow these steps:

### 1. Install Dependencies
It's recommended to use Conda or a Python virtual environment:
```bash
conda create -n hello-bitcoin python=3.10 -y
conda activate hello-bitcoin
pip install -r backend/requirements.txt
```

### 2. Configure Environment Variables
Copy the `.env.example` file to `.env`:
```bash
cp .env.example .env
```
The application automatically loads `.env` on startup via `python-dotenv` for database, queue, secret key, and sandbox settings.

### 3. Build the Docker Sandbox Image
The judge engine requires a pre-built Docker image for isolated runner execution:
```bash
docker build -f docker/Dockerfile.runner -t hello-bitcoin-runner ./docker
```

### 4. Start Redis Broker
A running Redis instance is required for rate limiting and managing the job queue:
```bash
docker run -d --name hello-bitcoin-redis -p 6379:6379 redis:7-alpine
```

### 5. Initialize & Seed Database
Seed the default problems, test cases, and initial admin account:
```bash
cd backend
python scripts/seed.py
```

### 6. Start Services
Run the web server and the background judge worker concurrently:

* **Terminal 1 (Web API Server & Frontend):**
  ```bash
  conda activate hello-bitcoin
  cd backend
  uvicorn main:app --port 8001 --reload
  ```
* **Terminal 2 (ARQ Worker Queue):**
  ```bash
  conda activate hello-bitcoin
  cd backend
  arq worker.WorkerSettings
  ```

### 7. Access the Site
* **Web UI & Frontend:** Open your browser to [http://localhost:8001](http://localhost:8001).
* **Interactive API Docs:** [http://localhost:8001/docs](http://localhost:8001/docs).
* **Admin Login:** Log in with `admin@example.com` / `admin1234` (created by `seed.py`).

---

## Alternative: All-in-One Docker Compose Setup

To run everything in production-like containerized services (including a PostgreSQL database, Redis server, API, and Judge Worker):

1. **Configure `.env`:**
   ```bash
   cp .env.example .env
   ```
   *(For production, ensure `SECRET_KEY` in `.env` is set to a secure random string, e.g. `openssl rand -hex 32`)*

2. **Start Services:**
   ```bash
   docker compose up --build
   ```
   *Note: Database migrations run automatically on startup via Alembic inside the API container.*

3. **Seed the Database:**
   Once the services are up and healthy, run the seed script inside the running API container:
   ```bash
   docker compose exec api python scripts/seed.py
   ```

4. **Access the Site:**
   * **Web UI:** Open your browser to [http://localhost:8001](http://localhost:8001).
   * **Admin Login:** Log in with `admin@example.com` / `admin1234`.

---

## Running Automated Tests

Run the full automated test suite:

```bash
cd backend
pytest tests/ -v
```

---

## Stress Test Results

> **Environment:** MacBook · 3× ARQ worker replicas · Docker Compose

### Overview

| Metric | Value |
|---|---|
| Total Submissions | 2,500 |
| HTTP Phase Time | 9.46 s |
| HTTP Throughput | **264.3 req/s** |
| Average Request Latency | 375 ms |
| Successful HTTP Requests | 2,500 / 2,500 (100%) |
| Total Judging Time | 260.34 s |
| Judging Throughput | **9.60 verdicts/sec** |

### Per-Language Breakdown

| Language | Submissions | Success | Failed | Avg Latency |
|---|---|---|---|---|
| Python 3 | 836 | 836 | 0 | 0.371 s |
| JavaScript | 832 | 832 | 0 | 0.371 s |
| Rust | 832 | 832 | 0 | 0.383 s |

> **Run the stress test:**
> ```bash
> pytest backend/tests/stress_test.py -v -s
> ```
