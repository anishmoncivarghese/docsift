from pydantic import BaseModel, Field

from docsift.core.models import Chunk


class HealthResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    version: str


class JobAccepted(BaseModel):
    job_id: str
    document_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    document_id: str | None = Field(
        default=None,
        description=(
            "Content address of the uploaded file. Assigned at submission, "
            "before conversion runs, so it is present even when the job "
            "later fails. Clients must check status == 'succeeded' before "
            "fetching the document by this id."
        ),
    )
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: str


class ChunksResponse(BaseModel):
    document_id: str
    chunks: list[Chunk]
