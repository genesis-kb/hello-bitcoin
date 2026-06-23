# Programming Bitcoin Online Judge (BTC-OJ)

Welcome to BTC-OJ! This platform is designed to help you practice and verify your solutions to the cryptography exercises presented in *Programming Bitcoin*.

## Features
- **Core Backend**: FastAPI, SQLAlchemy models, JWT auth.
- **Docker Sandbox Runner**: Secure, isolated code execution.
- **Async Background Worker**: ARQ queue consumer for parallel code evaluation and testing.
- **Code Submission Interface**: In-browser code editor and submission history table (`frontend/problem.html`, `frontend/submissions.html`).

## Local Development Setup

### 1. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 2. Build the Docker Sandbox Image
```bash
cd docker
docker build -t hello-bitcoin-runner -f Dockerfile.runner .
```

### 3. Start Redis Broker
A running Redis instance is required for rate limiting and managing the background job queue:
```bash
docker run -d --name hello-bitcoin-redis -p 6379:6379 redis:7-alpine
```

### 4. Initialize & Seed Database
```bash
cd backend
python scripts/seed.py
```

### 5. Start Services
You will need to run the web server and the background judge worker concurrently:

* **Terminal 1 (Web API Server & Frontend):**
  ```bash
  cd backend
  uvicorn main:app --port 8001 --reload
  ```
* **Terminal 2 (ARQ Worker Queue):**
  ```bash
  cd backend
  arq worker.WorkerSettings
  ```

### 6. Access the Site
* **Web UI:** Open your browser to [http://localhost:8001/index.html](http://localhost:8001/index.html).
* **Usage:** Click on a problem, write a Python solution in the editor, and click "Submit". View your history on the "My Submissions" page.
