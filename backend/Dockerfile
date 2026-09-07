FROM python:3.11-slim-bookworm

WORKDIR /app

# System deps for docker-py (needs a Docker CLI or at minimum the SDK deps)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root for principle of least privilege
RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
