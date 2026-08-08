# Configuration

Every setting is an environment variable. There is no config file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DOCSIFT_DATA_DIR` | `~/.local/share/docsift` | SQLite database and stored documents. |
| `DOCSIFT_CACHE_DIR` | `~/.cache/docsift` | Disposable conversion-result cache. |
| `DOCSIFT_MAX_UPLOAD_BYTES` | `52428800` (50 MB) | Upload size ceiling; can be raised or lowered. |
| `DOCSIFT_JOB_WORKERS` | `2` | Background conversion threads. |
| `DOCSIFT_MAX_PENDING_JOBS` | `32` | Queued + in-flight job ceiling; `POST /v1/documents` returns `503` past it. |
| `DOCSIFT_API_KEY` | unset | Optional shared secret required as `X-API-Key` on `/v1/*` routes. |
| `DOCSIFT_PUBLIC_URL` | `http://127.0.0.1:8000` | Reachable base URL advertised in OpenAPI and Swagger connector documents. |

Values are read when they are used, not cached at import, so changing one and
restarting the process is always enough.
