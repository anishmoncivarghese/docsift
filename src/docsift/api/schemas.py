from pydantic import BaseModel


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
    document_id: str | None = None
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: str
