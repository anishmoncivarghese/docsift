from pydantic import BaseModel, Field


class CleanOptions(BaseModel):
    remove_image_refs: bool = True
    keep_page_markers: bool = True
    #: Remove repeated running headers/footers (FR-06). Detection is
    #: position-aware: a line only counts as furniture when it recurs at a
    #: page boundary (within 3 lines of a page break or the document's start
    #: or end) at least `max(furniture_min_repeats, page_count // 2)` times.
    #: Documents with no page breaks are left untouched, since without pages
    #: there is no header/footer to remove — repeated body text (e.g. form
    #: boilerplate like "Not applicable") is never treated as furniture.
    remove_furniture: bool = True
    furniture_min_repeats: int = 3


class ChunkOptions(BaseModel):
    max_tokens: int = 1000
    overlap_tokens: int = 100


class ConversionOptions(BaseModel):
    clean: CleanOptions = Field(default_factory=CleanOptions)
    chunk: ChunkOptions = Field(default_factory=ChunkOptions)
