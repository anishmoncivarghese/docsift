from pydantic import BaseModel, Field


class CleanOptions(BaseModel):
    remove_image_refs: bool = True
    keep_page_markers: bool = True
    remove_furniture: bool = True
    furniture_min_repeats: int = 3


class ChunkOptions(BaseModel):
    max_tokens: int = 1000
    overlap_tokens: int = 100


class ConversionOptions(BaseModel):
    clean: CleanOptions = Field(default_factory=CleanOptions)
    chunk: ChunkOptions = Field(default_factory=ChunkOptions)
