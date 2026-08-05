FROM python:3.12-slim

# uv installs dependencies; the image runs the API as a non-root user (NFR-04).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --locked --extra markitdown --extra api --no-dev

RUN useradd --create-home --uid 10001 docsift \
    && mkdir -p /data \
    && chown -R docsift:docsift /app /data
USER docsift

ENV DOCSIFT_DATA_DIR=/data \
    DOCSIFT_CACHE_DIR=/data/cache \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "docsift.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
