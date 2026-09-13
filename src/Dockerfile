# Phase 0 single-stage image for the PDF QA system backend skeleton.
# Later phases (13) will introduce multi-stage builds and docker-compose.

FROM python:3.11-slim

WORKDIR /app

# Copy dependency manifest first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source and alembic configuration.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Run migrations at container start, then launch the API.
# DATABASE_URL etc. are injected via environment at runtime (.env / compose).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]