# Programming Bitcoin Online Judge (BTC-OJ)

Welcome to BTC-OJ! This platform is designed to help you practice and verify your solutions to the cryptography exercises presented in *Programming Bitcoin*.

## Features
- **Docker Sandbox Runner**: Secure, isolated code execution via a background ARQ worker queue.
- **Live Code Submission**: In-browser code editor with real-time SSE evaluation updates.
- **Admin Problem Dashboard**: Polygon-style problem creator for content management.
- **Admin User Management**: Internal portal to view users and manage role-based access control (RBAC).

## Local Development Setup

### 1. Install Dependencies & Build Docker Image
```bash
pip install -r backend/requirements.txt
cd docker
docker build -t hello-bitcoin-runner -f Dockerfile.runner .
```

### 2. Start Redis & Initialize DB
```bash
docker run -d --name hello-bitcoin-redis -p 6379:6379 redis:7-alpine
cd backend
python scripts/seed.py
```

### 3. Start Services
* **Terminal 1 (API):** `cd backend && uvicorn main:app --port 8001 --reload`
* **Terminal 2 (Worker):** `cd backend && arq worker.WorkerSettings`

### 4. Access the Site
* **Web UI:** [http://localhost:8001/index.html](http://localhost:8001/index.html).
* **Admin Access:** Log in as `admin@example.com` / `admin1234`. Go to the Admin panel -> Users tab to manage permissions.
