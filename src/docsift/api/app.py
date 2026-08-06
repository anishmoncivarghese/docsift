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
import os
import secrets
import sqlite3
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from docsift import __version__
from docsift.api.schemas import (
    ChunksResponse,
    HealthResponse,
    JobAccepted,
    JobStatusResponse,
    SearchResponse,
    VersionResponse,
)
from docsift.core.config import get_settings
from docsift.core.exceptions import (
    SearchQueryError,
    SearchUnavailableError,
    ServiceUnavailableError,
    UnsupportedFileError,
)
from docsift.core.models import ConversionResult
from docsift.engines.router import SUPPORTED_SUFFIXES, valid_engine_choices
from docsift.services import job_service, search_service
from docsift.storage import cache, database, documents

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


class ApiKeyMiddleware:
    """Protect API routes before FastAPI reads or parses the request body."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        configured = get_settings().api_key
        submitted = dict(scope.get("headers") or {}).get(b"x-api-key")
        accepted = configured is None or (
            submitted is not None
            and secrets.compare_digest(submitted, configured.encode("utf-8"))
        )
        if accepted:
            await self.app(scope, receive, send)
            return

        body = b'{"detail":"invalid or missing API key"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    job_service.startup()
    yield
    job_service.shutdown()


def _public_url() -> str:
    """Base URL advertised in the OpenAPI document.

    A custom connector needs a host, and Swagger 2.0 requires one, so the
    document cannot rely on the request's own origin the way a browser client can.
    """
    return os.environ.get("DOCSIFT_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


def create_app() -> FastAPI:
    app = FastAPI(
        title="DocSift",
        version=__version__,
        summary="Convert documents once. Give agents only what they need.",
        description=(
            "Convert PDFs and Office documents into clean Markdown and "
            "token-budgeted chunks, then search them. Conversion is "
            "asynchronous: upload returns a job id immediately and the caller "
            "polls until the job succeeds."
        ),
        servers=[{"url": _public_url(), "description": "DocSift service"}],
        lifespan=lifespan,
    )
    app.add_middleware(BodySizeLimitMiddleware)
    # Starlette wraps middleware in reverse registration order, so this guard
    # runs before the content-length guard and FastAPI's multipart parser.
    app.add_middleware(ApiKeyMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _content_safe_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default handler for a rejected query/body parameter --
        # e.g. `q` over the search endpoint's max_length -- includes the
        # rejected value verbatim in an "input" field. That would undo the
        # point of capping `q`: an overlong query must be rejected without
        # ever being echoed back. Strip "input" from every validation error
        # uniformly, not just on the search route, so the same guarantee
        # holds for any current or future caller-supplied field.
        errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

    @app.get(
        "/health",
        response_model=HealthResponse,
        operation_id="getHealth",
        summary="Check service health",
        description=(
            "Return ok when the service is running. Use this to verify connectivity "
            "before uploading a document."
        ),
    )
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/version",
        response_model=VersionResponse,
        operation_id="getVersion",
        summary="Get service version",
        description=(
            "Return the running DocSift version. Useful for confirming which release "
            "a deployment is on."
        ),
    )
    def version() -> VersionResponse:
        return VersionResponse(version=__version__)

    @app.post(
        "/v1/documents",
        response_model=JobAccepted,
        status_code=202,
        operation_id="uploadDocument",
        summary="Upload a document for conversion",
        description=(
            "Accept a PDF or Office document and start converting it in the background. "
            "Returns immediately with a job id and a document id. Conversion can take "
            "minutes, so poll the job with getJobStatus until its status is succeeded, "
            "then retrieve the result. Do not assume the document is ready when this returns."
        ),
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
            # The suffix is caller-controlled (it's derived from the
            # uploaded filename), so bound how much of it gets echoed back
            # rather than reflecting an arbitrarily long value verbatim.
            display_suffix = suffix if len(suffix) <= 40 else suffix[:40] + "..."
            raise HTTPException(
                status_code=415,
                detail=f"unsupported file type {display_suffix!r}",
            )
        # Validated before anything is written to disk, and the offending
        # value is never echoed back: an anonymous caller could otherwise post
        # an arbitrarily large `engine` string that ends up interpolated into
        # EngineNotAvailableError and stored verbatim in jobs.error.
        if engine not in valid_engine_choices():
            raise HTTPException(status_code=400, detail="unknown engine")

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
        except Exception:
            # Any failure here means no job was queued to eventually clean
            # this up itself (_run's finally only runs for jobs that actually
            # started) -- unlink before propagating or the original leaks
            # into data_dir/uploads indefinitely.
            target.unlink(missing_ok=True)
            raise
        return JobAccepted(job_id=job_id, document_id=document_id, status="queued")

    def _load_or_404(document_id: str) -> ConversionResult:
        try:
            result = documents.load_result(document_id)
        except UnsupportedFileError:
            # A malformed id names a resource that cannot exist.
            raise HTTPException(status_code=404, detail="document not found") from None
        if result is None:
            raise HTTPException(status_code=404, detail="document not found")
        return result

    @app.get(
        "/v1/jobs/{job_id}",
        response_model=JobStatusResponse,
        operation_id="getJobStatus",
        summary="Check conversion progress",
        description=(
            "Return the status of a conversion job: queued, processing, succeeded or failed. "
            "Poll this after uploadDocument until the status is succeeded or failed. The "
            "document id is present even when the job fails, so always check the status "
            "before retrieving the document."
        ),
    )
    def get_job(job_id: str) -> JobStatusResponse:
        record = job_service.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return JobStatusResponse(
            job_id=record.job_id,
            status=record.status,
            document_id=record.document_id,
            error=record.error,
        )

    @app.get(
        "/v1/documents/{document_id}",
        response_model=ConversionResult,
        operation_id="getDocument",
        summary="Get the full conversion result",
        description=(
            "Return the complete conversion result for a document, including its Markdown, "
            "every chunk, and conversion metrics. Prefer searchDocument when you only need "
            "the parts relevant to a question, because this returns the whole document."
        ),
    )
    def get_document(document_id: str) -> ConversionResult:
        return _load_or_404(document_id)

    @app.get(
        "/v1/documents/{document_id}/markdown",
        response_class=Response,
        operation_id="getDocumentMarkdown",
        summary="Get the document as Markdown",
        description=(
            "Return the cleaned Markdown for a converted document as plain text. This is "
            "the whole document; prefer searchDocument when you only need relevant sections."
        ),
    )
    def get_document_markdown(document_id: str) -> Response:
        result = _load_or_404(document_id)
        return Response(content=result.document.markdown, media_type="text/markdown; charset=utf-8")

    @app.get(
        "/v1/documents/{document_id}/chunks",
        response_model=ChunksResponse,
        operation_id="getDocumentChunks",
        summary="Get all document chunks",
        description=(
            "Return every chunk of a converted document with its section path, page numbers "
            "and token count. This is the whole document; prefer searchDocument when you "
            "only need relevant sections."
        ),
    )
    def get_document_chunks(document_id: str) -> ChunksResponse:
        result = _load_or_404(document_id)
        return ChunksResponse(document_id=result.document_id, chunks=result.chunks)

    @app.get(
        "/v1/documents/{document_id}/search",
        response_model=SearchResponse,
        operation_id="searchDocument",
        summary="Search within a document",
        description=(
            "Return the chunks of one document most relevant to a keyword or quoted-phrase "
            "query, ranked and capped by a token budget. Use this instead of retrieving the "
            "whole document when answering a question about it. Supports quoted phrases and "
            "optional adjacent-chunk context."
        ),
    )
    def search_document_endpoint(
        document_id: str,
        q: Annotated[
            str, Query(min_length=1, max_length=1024, description="Keyword or quoted phrase")
        ],
        limit: Annotated[int, Query(ge=1, le=20)] = 5,
        max_tokens: Annotated[int, Query(ge=1, le=20_000)] = 5000,
        context: Annotated[int, Query(ge=0, le=2)] = 0,
    ) -> SearchResponse:
        # Confirm the document exists via the metadata row -- an indexed
        # primary-key lookup, same as the CLI -- rather than parsing the
        # complete stored result (full markdown plus every chunk) just to
        # throw it away. `documents.document_dir` still validates the id's
        # shape first, so a malformed id 404s without ever touching sqlite.
        try:
            documents.document_dir(document_id)
        except UnsupportedFileError:
            raise HTTPException(status_code=404, detail="document not found") from None
        if database.get_document(document_id) is None:
            raise HTTPException(status_code=404, detail="document not found")
        try:
            indexed_count = database.count_indexed_chunks(document_id)
        except sqlite3.OperationalError:
            # document_chunks doesn't exist -- this SQLite build lacks FTS5
            # (see init_db()). Skip the not-indexed check below and let
            # search_service report unavailability explicitly.
            indexed_count = None
        if indexed_count == 0:
            # Rare path: only now is the full stored result worth loading,
            # to tell a document that legitimately has no chunks apart from
            # one converted before search shipped (or whose index rows were
            # otherwise lost) -- indistinguishable from a genuine miss
            # unless flagged separately. An empty 200 here would be silent
            # data loss from the caller's point of view.
            result = documents.load_result(document_id)
            if result is not None and result.chunks:
                raise HTTPException(
                    status_code=409,
                    detail="document is not indexed; re-upload it to index it",
                )
        try:
            return search_service.search_document(
                document_id,
                q,
                limit=limit,
                max_tokens=max_tokens,
                context=context,
            )
        except SearchQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SearchUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.delete(
        "/v1/documents/{document_id}",
        status_code=204,
        operation_id="deleteDocument",
        summary="Delete a document",
        description=(
            "Permanently remove a document, its stored files, its search index and any cached "
            "copies. Cancels conversion if it is still running. This cannot be undone."
        ),
    )
    def delete_document(document_id: str) -> Response:
        # Flag any still-running job for this document before touching the
        # filesystem: a delete that lands while conversion is in progress must
        # not be undone by the worker finishing afterwards and writing a fresh
        # result. See job_service._run's cancel_requested check.
        cancelled = database.request_cancel(document_id)
        try:
            removed_files = documents.delete_document_files(document_id)
        except UnsupportedFileError:
            raise HTTPException(status_code=404, detail="document not found") from None
        except OSError as exc:
            raise HTTPException(status_code=500, detail="failed to delete document") from exc
        removed_row = database.delete_document(document_id)
        removed_cache, failed_cache = cache.delete_entries_for_document(document_id)
        if failed_cache:
            # A readable copy may still exist in the cache -- reporting 204
            # here would say deletion succeeded when it didn't necessarily.
            raise HTTPException(status_code=500, detail="failed to purge cached copies")
        if cancelled and not (removed_files or removed_row or removed_cache):
            # Nothing existed yet to delete, but a job was in flight -- a 404
            # would tell the client something false (that there was never
            # anything here), so say deletion was accepted instead.
            return Response(status_code=202)
        if not (removed_files or removed_row or removed_cache):
            raise HTTPException(status_code=404, detail="document not found")
        return Response(status_code=204)

    if get_settings().api_key is not None:

        def custom_openapi() -> dict:
            if app.openapi_schema:
                return app.openapi_schema
            schema = get_openapi(
                title=app.title,
                version=app.version,
                summary=app.summary,
                description=app.description,
                routes=app.routes,
                servers=app.servers,
            )
            schema.setdefault("components", {})["securitySchemes"] = {
                "ApiKeyHeader": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            }
            for path, path_item in schema.get("paths", {}).items():
                if not path.startswith("/v1/"):
                    continue
                for operation in path_item.values():
                    operation["security"] = [{"ApiKeyHeader": []}]
            app.openapi_schema = schema
            return schema

        app.openapi = custom_openapi

    return app


app = create_app()
