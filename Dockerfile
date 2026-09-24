FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install .

COPY .env.example ./.env.example
RUN mkdir -p /app/data/jobs

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000
VOLUME ["/app/data"]

CMD ["sh", "-c", "uvicorn gpx_route_generator.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
