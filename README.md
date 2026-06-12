# Programming Bitcoin Online Judge (BTC-OJ)

Welcome to BTC-OJ! This platform is designed to help you practice and verify your solutions to the cryptography exercises presented in *Programming Bitcoin*.

## Features
- **Core Backend**: FastAPI, SQLAlchemy models, Pydantic schemas, JWT auth.
- **Database Seeding**: A `scripts/seed.py` utility to populate the database with problems and an admin user.
- **Frontend**: A minimal interface including `index.html` (Problem List) and `login.html`.

## Local Development Setup

To run the platform locally, follow these steps:

### 1. Install Dependencies
It's recommended to use Conda or a virtual environment:
```bash
conda create -n hello-bitcoin python=3.11 -y
conda activate hello-bitcoin
pip install -r backend/requirements.txt
```

### 2. Initialize & Seed Database
Ensure tables are created and the default problems and admin credentials are seeded:
```bash
cd backend
python scripts/seed.py
```

### 3. Start Services
Start the web server:
```bash
cd backend
uvicorn main:app --port 8001 --reload
```

### 4. Access the Site
* **Web UI:** Open your browser to [http://localhost:8001/index.html](http://localhost:8001/index.html).
* **Admin Login:** Log in with `admin@example.com` / `admin1234`. You can browse the homepage and verify the seeded problems appear.
