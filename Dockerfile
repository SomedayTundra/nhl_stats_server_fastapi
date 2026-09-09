# matches the Python the project is developed against (see .venv). Drop to 3.13-slim only if a
# dependency is missing a 3.14 wheel.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# single worker: the on-demand-farm dedupe locks in app/routes/nhl_standings.py are per-process,
# and the routes call synchronous pymongo so extra workers buy little at hobby traffic anyway.
# --ws none: the API has no WebSocket routes, so skip uvicorn's ws backend entirely.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--ws", "none"]
