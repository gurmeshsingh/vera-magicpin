# Single-stage: the service has no build step and no model dependency.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# The judge polls /v1/healthz every 60s and three consecutive failures end the
# run, so the container declares its own liveness on the same endpoint.
HEALTHCHECK --interval=20s --timeout=4s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/v1/healthz',timeout=3).status==200 else 1)"

# Render injects PORT and expects the process to bind it. Hardcoding 8080
# means the health check never connects and the deploy is marked failed.
ENV PORT=8080
EXPOSE 8080

# A single worker, deliberately.
#
# State lives in memory and the contract forbids losing it mid-test. Two
# workers would mean two independent context stores, each holding half the
# pushes, each reporting the wrong count from /v1/healthz -- and the warmup
# gate checks that count against all 255 base contexts.
CMD ["sh", "-c", "uvicorn vera.api.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
