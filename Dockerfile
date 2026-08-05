FROM python:3.12-slim

# uv installs dependencies; the image runs the API as a non-root user (NFR-04).
# Pinned (not :latest) so this build is reproducible like every other pinned
# dependency in the project (uv.lock, engine extras).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

# Dependencies install before source is copied in, so an edit to src/ only
# invalidates the layers below this point -- not the (slow) dependency
# resolution above it. --no-install-project defers building docsift itself,
# since that needs src/ to exist; the second sync below is fast because
# every dependency is already installed.
RUN uv sync --locked --extra markitdown --extra api --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --extra markitdown --extra api --no-dev

RUN useradd --create-home --uid 10001 docsift \
    && mkdir -p /data \
    && chown -R docsift:docsift /app /data
USER docsift

ENV DOCSIFT_DATA_DIR=/data \
    DOCSIFT_CACHE_DIR=/data/cache \
    PATH="/app/.venv/bin:$PATH"

# A host bind mount at /data arrives root-owned, and uid 10001 cannot create
# the database there -- a named volume (or a pre-chowned bind mount) is
# required. See README's Docker section.
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
CMD ["uvicorn", "docsift.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
