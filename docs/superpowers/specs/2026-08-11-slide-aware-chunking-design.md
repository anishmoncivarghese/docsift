# Slide-aware chunking for PowerPoint

**Date:** 2026-08-11
**Status:** draft, awaiting approval

## Problem

DocSift already converts PPTX well. MarkItDown extracts slide titles as
headings, bullets, real Markdown tables, and speaker notes, and it marks slide
boundaries. A three-slide test deck produces:

```
<!-- Slide number: 1 -->
# Quarterly Business Review
Revenue increased 12% YoY

### Notes:
Speaker note: emphasise APAC risk here.

<!-- Slide number: 2 -->
# Key Metrics
| Metric | Value |
| --- | --- |
| Revenue | $42M |
```

The chunks that come out of it carry nothing:

```
chunk c000 | pages: [] | section_path: [] | page_count: None
```

So retrieval over a 60-slide deck returns text with no way to say which slide it
came from. Citation is the thing that distinguishes DocSift from a plain local
RAG tool, and on PowerPoint it silently does not work.

### Why

The pipeline already has a page-attribution mechanism, and PPTX misses it by a
naming accident:

1. `DoclingEngine` asks for `<!-- page-break -->` placeholders
   (`docling_engine.py:110`).
2. The cleaner turns those into numbered `<!-- page: N -->` markers, counts
   pages, and records boundaries for furniture removal (`cleaner.py:125-137`).
3. The chunker matches `^<!-- page: (\d+) -->$`, tracks the current page, drops
   the marker line, and puts the result in `Chunk.pages` (`chunker.py:8`).

MarkItDown emits `<!-- Slide number: N -->`. Nothing matches it, so it is never
recognised as a marker. It falls through to the paragraph branch and becomes
ordinary text.

That single mismatch causes all three symptoms:

- **No slide numbers.** `pages` stays empty.
- **No section path.** `section_path` is taken from the chunk's first non-heading
  block. That block is now the stray marker line, whose heading path was
  captured before any heading was seen — so it is empty. The slide title is
  present in the document and still never reported.
- **Marker text in chunks.** Every `<!-- Slide number: N -->` line is chunk
  content: wasted tokens, and visible noise in search results.

## Design

**Normalise the marker at the engine boundary.** `MarkItDownEngine.convert`
rewrites `<!-- Slide number: N -->` into `<!-- page: N -->` before returning, and
sets `EngineOutput.page_count` to the highest slide number seen.

Nothing else changes. The cleaner already protects `<!-- page: N -->` lines from
furniture removal (`cleaner.py:55`), and the chunker already attributes and drops
them. **The chunker is not modified.**

### Why at the engine and not in the chunker

The marker format is a fact about MarkItDown, and `CLAUDE.md` rule 4 keeps
engine-specific knowledge inside `engines/`. Teaching the chunker a second
pattern would put a vendor's output format in a module that is supposed to
consume the neutral schema, and would leave the next engine to add a third.

### Why `pages` and not a new `slides` field

For a deck, page number *is* slide number. Adding a parallel field would fork
every downstream consumer — search, the MCP tools, the HTTP schema, the
comparison report — for a synonym. The field stays `pages`; the README says that
for a presentation it means slides.

## Decisions

**Slide numbers are used as MarkItDown reports them, never renumbered.** If a
deck skips numbers, the citation should match what the user sees in PowerPoint,
not a recount.

**`keep_page_markers=False` must also strip markers that arrived from an
engine.** Today the cleaner only *inserts* markers, so with the option off a
Docling PDF has none while a PPTX would keep MarkItDown's. That is an
inconsistency this change would otherwise create. The cleaner drops any
pre-existing `<!-- page: N -->` line when the option is off, so the two engines
behave the same.

**A deck with no markers behaves exactly as today** — no attribution, no error.
Older MarkItDown versions, or formats that never had slides, must not break.

**docx and xlsx are unaffected.** They carry no slide markers, so the rewrite is
a no-op for them; a test pins that.

## Testing

- A rewrite unit test: `<!-- Slide number: 7 -->` becomes `<!-- page: 7 -->`,
  and `page_count` is the highest number seen.
- A **60-slide fixture** (`tests/fixtures/deck.pptx`, with a committed
  `make_deck.py` alongside it, following `scanned.pdf`): every chunk has a
  non-empty `pages`, values are non-decreasing across chunks, and a phrase
  placed only on slide 14 lands in a chunk whose `pages` is `[14]`.
- `section_path` is non-empty and contains the slide title.
- No chunk text contains `Slide number` or `<!-- page:`.
- A pptx whose markdown has no markers converts with `pages == []` and does not
  raise.
- A docx conversion is byte-identical to today's output.
- `keep_page_markers=False` leaves no markers in the Markdown for either engine.

## Out of scope

Deliberately not in this change:

- **Images and OCR inside slides.** MarkItDown does not extract them. Routing
  PPTX through Docling would, at the cost of the whole PyTorch stack for a
  format that currently needs none.
- **Diagram semantics.** A slide with three boxes and two arrows extracts as
  three labels; the arrows are lost. Confirmed on the test deck. This should be
  documented as a known limitation, not engineered around.
- **Visual descriptions via a vision model.** Requires either an API, which ends
  "nothing leaves your machine", or a local VLM, which adds gigabytes to the
  install that is already the main adoption objection.
- **Document generation** (Markdown → PPTX/DOCX/PDF). A different product with
  different users and failure modes; it shares no code with retrieval.
