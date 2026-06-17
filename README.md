# Programming Bitcoin Online Judge (BTC-OJ)

Welcome to BTC-OJ! This platform is designed to help you practice and verify your solutions to the cryptography exercises presented in *Programming Bitcoin*.

## Features
- **Core Backend**: FastAPI, SQLAlchemy models, JWT auth.
- **Docker Sandbox Runner**: Pre-built Docker container for secure, isolated code execution (`docker/Dockerfile.runner`).
- **Judge Core**: The `backend/judge/` module to handle container pooling, code running, and test case validation.
- **Frontend**: A minimal interface to view the problem list and log in.

## Local Development Setup

### 1. Install Dependencies
```bash
conda create -n hello-bitcoin python=3.11 -y
conda activate hello-bitcoin
pip install -r backend/requirements.txt
```

### 2. Build the Docker Sandbox Image
The judge engine requires a pre-built Docker image for isolated runner execution:
```bash
cd docker
docker build -t hello-bitcoin-runner -f Dockerfile.runner .
```

### 3. Initialize & Seed Database
```bash
cd backend
python scripts/seed.py
```

### 4. Start Services
Start the web server:
```bash
cd backend
uvicorn main:app --port 8001 --reload
```

### 5. Access the Site
* **Web UI:** Open your browser to [http://localhost:8001/index.html](http://localhost:8001/index.html).
* **Testing the Judge:** The judge core is functional in the backend. You can manually test it by opening a Python shell in `backend`, importing `ContainerPool`, and running code against it.
