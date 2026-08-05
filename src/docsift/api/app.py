"""DocSift's FastAPI app: health, version, and the upload endpoint.

Known gap in the upload size guard: `BodySizeLimitMiddleware` below rejects an
oversized body before it is buffered, but only when the client sends an honest
`Content-Length` header. A request with no `Content-Length` (chunked
transfer-encoding) or an understated one is still fully buffered by
Starlette's multipart parser before the in-handler streaming check gets a
chance to reject it -- that check is a correctness backstop for a dishonest
or missing header, not a performance guarantee. See README's Known
limitations for the user-facing note.
"""

import json
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from docsift import __version__
from docsift.api.schemas import HealthResponse, JobAccepted, VersionResponse
from docsift.core.config import get_settings
from docsift.core.exceptions import ServiceUnavailableError
from docsift.engines.router import SUPPORTED_SUFFIXES
from docsift.services import job_service

_CHUNK = 1 << 20


class BodySizeLimitMiddleware:
    """Reject an oversized body before FastAPI's form parser buffers it.

    FastAPI resolves `UploadFile = File(...)` by calling `request.form()`, which
    drains and spools the entire body before the route function runs -- so a check
    inside the handler cannot stop the server paying for the whole upload. This
    sits in front of that and answers 413 without reading the body.

    This only catches a client that reports its size honestly via
    `Content-Length`. A chunked request (no `Content-Length`) or one that
    understates its size passes through to the handler's own streaming check,
    which is correct but -- because FastAPI has already buffered the body by
    the time that check runs -- no longer early-aborting.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        max_bytes = get_settings().max_upload_bytes
        declared = dict(scope.get("headers") or {}).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > max_bytes
            except ValueError:
                too_big = False
            if too_big:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": json.dumps(
                            {"detail": f"upload exceeds {max_bytes} bytes"}
                        ).encode(),
                    }
                )
                return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    job_service.startup()
    yield
    job_service.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DocSift",
        version=__version__,
        summary="Convert documents once. Give agents only what they need.",
        lifespan=lifespan,
    )
    app.add_middleware(BodySizeLimitMiddleware)

    @app.get("/health", response_model=HealthResponse, operation_id="getHealth")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/version", response_model=VersionResponse, operation_id="getVersion")
    def version() -> VersionResponse:
        return VersionResponse(version=__version__)

    @app.post(
        "/v1/documents",
        response_model=JobAccepted,
        status_code=202,
        operation_id="uploadDocument",
    )
    async def upload_document(
        file: UploadFile = File(...),
        engine: str = Form("auto"),
    ) -> JobAccepted:
        settings = get_settings()
        # Only the suffix of the client's filename is ever used; the name itself
        # never becomes a path component, so `../../evil.txt` cannot escape.
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=415,
                detail=f"unsupported file type '{suffix}'",
            )

        uploads = settings.data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=uploads, suffix=suffix, delete=False)
        target = Path(handle.name)
        written = 0
        try:
            while block := await file.read(_CHUNK):
                written += len(block)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds {settings.max_upload_bytes} bytes",
                    )
                handle.write(block)
            handle.close()
            if written == 0:
                raise HTTPException(status_code=400, detail="uploaded file is empty")
        except HTTPException:
            handle.close()
            target.unlink(missing_ok=True)
            raise

        try:
            # job_service.submit hashes the whole file and writes to sqlite --
            # both blocking I/O -- so it runs off the event loop to avoid
            # serializing concurrent uploads behind it.
            job_id, document_id = await run_in_threadpool(
                job_service.submit, target, file.filename or target.name, engine
            )
        except ServiceUnavailableError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JobAccepted(job_id=job_id, document_id=document_id, status="queued")

    return app


app = create_app()
