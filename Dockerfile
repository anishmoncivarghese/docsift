FROM python:3.12-slim

# uv installs dependencies; the image runs the API as a non-root user (NFR-04).
# Pinned (not :latest) so this build is reproducible like every other pinned
# dependency in the project (uv.lock, engine extras). Must be new enough to read
# uv.lock's revision -- an older uv rejects the lockfile outright under --locked.
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

# Both engines are installed: routing sends every PDF to Docling with no
# fallback, so an image without the docling extra fails on exactly the file type
# this service exists for. `--group cpu-torch` is what pins torch to the CPU
# wheels (see pyproject.toml) instead of the CUDA build's several GB of GPU
# runtimes.
#
# Dependencies install before source is copied in, so an edit to src/ only
# invalidates the layers below this point -- not the (slow) dependency
# resolution above it. --no-install-project defers building docsift itself,
# since that needs src/ to exist; the second sync below is fast because
# every dependency is already installed.
RUN uv sync --locked --extra markitdown --extra docling --extra api --group cpu-torch \
    --no-dev --no-install-project

RUN useradd --create-home --uid 10001 docsift \
    && mkdir -p /data /opt/tiktoken \
    && chown -R docsift:docsift /app /data /opt/tiktoken

ENV DOCSIFT_DATA_DIR=/data \
    DOCSIFT_CACHE_DIR=/data/cache \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    PATH="/app/.venv/bin:$PATH"

USER docsift

# Model weights are baked in rather than fetched on first use. Downloading them
# as the runtime user puts them in the same per-user cache Docling reads from at
# conversion time. Without this the first PDF after every deploy stalls for
# minutes, and the running container needs outbound access to Hugging Face --
# which a locked-down deployment may not have. This layer is large and slow; it
# sits above the source copy so editing src/ does not rebuild it.
RUN docling-tools models download \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

COPY --chown=docsift:docsift src ./src
RUN uv sync --locked --extra markitdown --extra docling --extra api --group cpu-torch --no-dev

# A host bind mount at /data arrives root-owned, and uid 10001 cannot create
# the database there -- a named volume (or a pre-chowned bind mount) is
# required. See README's Docker section.
VOLUME /data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
CMD ["uvicorn", "docsift.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
