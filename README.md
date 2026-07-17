# Programming Bitcoin Online Judge (BTC-OJ)

Welcome to BTC-OJ! This platform is designed to help you practice and verify your solutions to the cryptography exercises presented in *Programming Bitcoin* by Jimmy Song.

## Overview
- **Solve problems**: Write your solutions directly in the browser using the interactive CodeMirror editor.
- **Instant feedback**: Your code is executed in isolated, pre-warmed Docker containers against hidden test cases.
- **Multiple languages**: Supports Python 3 (primary), JavaScript, and Rust.
- **Admin Panel**: For instructors or administrators to manage problems, test cases, and users.

## How to Use the Platform

### 1. Registration & Login
Navigate to the top right and click **Login**. You can either log in to an existing account or switch to the **Register** tab to create a new one. Once authenticated, your submissions will be tracked.

### 2. Exploring Problems
The homepage lists all published problems, categorized by chapter. Click on a problem to open its workspace.

### 3. Solving a Problem
When you open a problem, you'll see a split layout:
- **Left Panel**: Contains the problem description, rules, and sample test cases.
- **Right Panel**: Contains the code editor. It is pre-filled with starter code. Do not change the class/function signatures provided in the starter code, as the judging harness relies on them.

**To Submit:**
1. Choose your language from the dropdown.
2. Fill in your solution (e.g., implementing the `__add__` method).
3. Click the **Submit** button.
4. Your code is evaluated instantly, and you'll see a verdict (e.g., `AC` for Accepted, `WA` for Wrong Answer, `CE` for Compile Error, etc.).

### 4. Verdicts Explained
- **AC (Accepted)**: Your solution passed all test cases!
- **WA (Wrong Answer)**: Your output didn't match the expected output.
- **TLE (Time Limit Exceeded)**: Your code ran too long. Check for infinite loops or inefficient algorithms.
- **RE (Runtime Error)**: Your code crashed or raised an exception during execution.
- **CE (Compile/Syntax Error)**: Your code failed to compile (or had a syntax error in Python/JS).

### 5. Viewing Submissions
Click on **My Submissions** to see a history of all your attempts. You can click on the problem ID in the table to return to the problem workspace.

## For Administrators

If your account has the `admin` role, you'll see an **⚙ Admin** link in the navigation bar.

### Admin Dashboard
The dashboard provides a high-level view of platform statistics (total users, submissions, etc.) and lists all problems.

### Problem Management (Polygon Style)
Click **+ New Problem** or **Edit** on an existing problem to open the problem editor.
- **General Tab**: Set the ID, title, time/memory limits, and write the description using Markdown.
- **Code Editors Tab**: Define the starter code (shown to users), the wrapper/harness code (appended to user submissions), and a custom checker (if the default exact-match checker is insufficient).
- **Test Cases Tab**: Create, edit, and categorize test cases. Mark cases as "Sample" if they should be visible to users in the problem description.

### User Management
The **Users** page allows you to view all registered users and promote/demote them to/from the admin role.

## Local Development Setup

To run the platform locally, follow these steps:

### 1. Install Dependencies
It's recommended to use Conda or a virtual environment:
```bash
conda create -n hello-bitcoin python=3.11 -y
conda activate hello-bitcoin
pip install -r backend/requirements.txt
```

### 2. Build the Docker Sandbox Image
The judge engine requires a pre-built Docker image for isolated runner execution:
```bash
docker build -f docker/Dockerfile.runner -t hello-bitcoin-runner ./docker
```

### 3. Start Redis Broker
A running Redis instance is required for rate limiting and managing the job queue:
```bash
docker run -d --name hello-bitcoin-redis -p 6379:6379 redis:7-alpine    
```

### 4. Initialize & Seed Database
Ensure tables are created and the default problems, test cases, and admin credentials are seeded:
```bash
cd backend
python scripts/seed.py
```

### 5. Start Services
You will need to run the web server and the background judge worker concurrently:

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

### 6. Access the Site
* **Web UI:** Open your browser to [http://localhost:8001](http://localhost:8001).
* **Admin Login:** Log in with `admin@example.com` / `admin1234`.

## Alternative: All-in-One Docker Compose Setup

To run everything in production-like containerized services (including a PostgreSQL database and a Redis server):

```bash
docker compose up --build
```
*Note: Database migrations run automatically on startup via Alembic inside the API container.*

2. **Seed the Database:**(If u wanna test admin side)
Once the services are up and healthy, run the seed script inside the running API container to register the default problems, test cases, and the admin user:
```bash
docker compose exec api python scripts/seed.py
```

### 4. Access the Site
* **Web UI:** Open your browser to [http://localhost:8001](http://localhost:8001).
* **Admin Login:** Log in with `admin@example.com` / `admin1234`.
