FROM python:3.11-slim-bookworm

# Build context is the repo root so the frontend can be baked into the image:
#   docker build -f backend/Dockerfile .

WORKDIR /app

# System deps for docker-py (needs a Docker CLI or at minimum the SDK deps)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# main.py serves static files from <app>/../frontend
COPY frontend/ /frontend/

# Run as non-root for principle of least privilege
RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
