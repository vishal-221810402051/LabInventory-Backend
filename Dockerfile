FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system appuser \
    && adduser --system --ingroup appuser appuser

COPY pyproject.toml README.md ./
RUN mkdir -p app tools \
    && touch app/__init__.py tools/__init__.py

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[dev]"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY tests ./tests
COPY tools ./tools

RUN mkdir -p /data/instance /data/uploads \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"

CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${API_PORT:-8000}"]
