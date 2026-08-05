import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from docsift import __version__
from docsift.api.schemas import HealthResponse, JobAccepted, VersionResponse
from docsift.core.config import get_settings
from docsift.core.exceptions import ServiceUnavailableError
from docsift.engines.router import SUPPORTED_SUFFIXES
from docsift.services import job_service

_CHUNK = 1 << 20


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
            job_id, document_id = job_service.submit(
                target, file.filename or target.name, engine=engine
            )
        except ServiceUnavailableError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return JobAccepted(job_id=job_id, document_id=document_id, status="queued")

    return app


app = create_app()
