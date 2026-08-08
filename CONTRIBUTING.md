# Contributing

Thanks for looking. DocSift is small and pre-1.0, so the bar is less about
process and more about not quietly breaking documents.

## Setup

DocSift uses [uv](https://docs.astral.sh/uv/). Python 3.12 is the development
version; CI also runs 3.11.

    uv sync --extra markitdown --extra api
    uv run docsift --help

Add `--extra docling` if you are working on the PDF path. It is a large install
(PyTorch and model weights), which is why it is optional.

## The gates

These are exactly what CI runs. Run them before opening a pull request:

    uv run ruff check .
    uv run ruff format --check .
    uv run pytest

Integration tests are deselected by default because they need real engines and
may download models. Run them deliberately:

    uv run pytest -m integration

**Tests must pass without Docling installed.** CI installs only the markitdown
and api extras, so anything that imports Docling at module level, or assumes a
PDF can be converted, breaks the default lane. Engine imports stay lazy, and
tests that need an engine skip cleanly when it is absent. If you have Docling
installed locally, check your work in an environment without it before assuming
you are done.

## What review will actually look for

**A test that fails before your fix.** For a bug fix, demonstrate the test is
red against the old code. A test that passes against the buggy code is not
protecting anything — this has caught real problems here more than once.

**No document content in error messages.** Conversion failures surface the
exception type only, never its text, because engine exceptions routinely embed
fragments of the document. The same applies to logs and to anything returned by
the API.

**Nothing silently loses document text.** Cleaning, chunking and de-duplication
all edit a document, and the recurring class of bug in this project is text
disappearing quietly — code fences split, headings dropped, repeated body lines
mistaken for page furniture. If you touch those paths, say in the pull request
what you did to convince yourself nothing was lost.

**Changes that reach the API surface stay documented.**
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) is deliberately blunt. If your change
removes a limitation, delete the entry. If it adds one, add it — an honest limitation is worth more
than a quiet surprise.

## Commits

Short imperative subject in lower case, prefixed by type: `fix:`, `feat:`,
`docs:`, `ci:`, `chore:`, `test:`. Explain *why* in the body when the reason is
not obvious from the diff. Keep unrelated changes in separate commits.

## Where design lives

- `docs/specs/` — what a release is meant to do.
- `docs/superpowers/plans/` — per-milestone implementation plans.
- `CHANGELOG.md` — what actually shipped.

Proposals for anything substantial are welcome as an issue before the code.
Small fixes need no ceremony.
