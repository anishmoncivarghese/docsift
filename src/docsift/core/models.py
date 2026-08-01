from datetime import datetime

from pydantic import BaseModel, Field


class ConversionWarning(BaseModel):
    code: str
    message: str


class SourceMetadata(BaseModel):
    filename: str
    media_type: str
    size_bytes: int
    sha256: str


class ConversionMetadata(BaseModel):
    engine: str
    engine_version: str
    docsift_version: str
    selection_reason: str
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    ocr_used: bool = False
    cached: bool = False


class DocumentContent(BaseModel):
    title: str | None = None
    page_count: int | None = None
    language: str | None = None
    markdown: str


class ConversionMetrics(BaseModel):
    characters: int
    words: int
    estimated_tokens: int


class Chunk(BaseModel):
    chunk_id: str
    text: str
    estimated_tokens: int = 0
    section_path: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)


class EngineOutput(BaseModel):
    """Raw, engine-agnostic output of a single engine run, pre-normalization."""

    markdown: str
    title: str | None = None
    page_count: int | None = None
    ocr_used: bool = False
    engine_version: str
    warnings: list[ConversionWarning] = Field(default_factory=list)


class ConversionResult(BaseModel):
    schema_version: str = "1"
    document_id: str
    source: SourceMetadata
    conversion: ConversionMetadata
    document: DocumentContent
    chunks: list[Chunk] = Field(default_factory=list)
    metrics: ConversionMetrics
    warnings: list[ConversionWarning] = Field(default_factory=list)
