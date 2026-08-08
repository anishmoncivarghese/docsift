"""The MCP server's logic, exercised without the MCP SDK installed.

Only `build_server` needs the SDK, so everything else here runs in the default
CI lane where the `mcp` extra is absent.
"""

from pathlib import Path

import pytest

from docsift import mcp_server


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point the data and cache directories at a scratch location."""
    monkeypatch.setenv("DOCSIFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFT_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def sample(tmp_path) -> Path:
    path = tmp_path / "note.md"
    path.write_text(
        "# Quarterly Report\n\nRevenue grew across every region this quarter.\n",
        encoding="utf-8",
    )
    return path


def test_missing_path_is_rejected_before_any_engine_runs():
    with pytest.raises(ValueError, match="path not found"):
        mcp_server.search_local("/definitely/not/here.pdf", "revenue")


def test_directory_is_not_a_document(tmp_path):
    with pytest.raises(ValueError, match="not a regular file"):
        mcp_server.convert_local(str(tmp_path))


def test_convert_reports_a_summary_and_never_the_markdown(sample):
    summary = mcp_server.convert_local(str(sample))

    assert summary["document_id"].startswith("doc_")
    assert summary["already_indexed"] is False
    # Every advertised key must exist -- an attribute renamed upstream should
    # fail here, not in an agent's tool call.
    for key in ("engine", "pages", "estimated_tokens", "chunks", "warnings"):
        assert key in summary, f"summary lost its {key!r} field"
    assert summary["estimated_tokens"] > 0
    # The whole point: a document's text must not ride back in the response.
    assert "Revenue grew" not in repr(summary)


def test_second_convert_recognises_the_document_instead_of_reconverting(sample):
    first = mcp_server.convert_local(str(sample))
    second = mcp_server.convert_local(str(sample))

    assert second["document_id"] == first["document_id"]
    assert second["already_indexed"] is True


def test_a_renamed_copy_is_the_same_document(sample, tmp_path):
    first = mcp_server.convert_local(str(sample))
    copy = tmp_path / "renamed.md"
    copy.write_bytes(sample.read_bytes())

    assert mcp_server.convert_local(str(copy))["document_id"] == first["document_id"]


def test_search_converts_on_first_use_and_returns_matching_chunks(sample):
    response = mcp_server.search_local(str(sample), "revenue")

    assert response["document_id"].startswith("doc_")
    assert response["results"], "expected the matching chunk"
    assert "Revenue grew" in response["results"][0]["text"]


def test_search_result_matches_the_library_for_the_same_query(sample):
    from docsift.services.search_service import search_document

    document_id = mcp_server.ensure_indexed(sample.resolve())
    direct = search_document(document_id, "revenue", limit=5, max_tokens=2000, context=0)
    through_tool = mcp_server.search_local(str(sample), "revenue")

    assert [r["chunk_id"] for r in through_tool["results"]] == [r.chunk_id for r in direct.results]


def test_a_query_matching_nothing_returns_no_results(sample):
    response = mcp_server.search_local(str(sample), "helicopter")

    assert response["results"] == []


def test_unexpected_failures_never_surface_document_content(sample, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("boom: Revenue grew across every region this quarter.")

    monkeypatch.setattr("docsift.services.search_service.search_document", explode, raising=True)

    with pytest.raises(RuntimeError) as caught:
        mcp_server.search_local(str(sample), "revenue")

    assert "Revenue grew" not in str(caught.value)
    assert "RuntimeError" in str(caught.value)


def test_defaults_match_the_cli_so_the_two_surfaces_agree():
    """A tighter budget here than the CLI starves the tool.

    Chunks routinely reach ~1,000 tokens, so a 2,000-token budget returns one
    chunk and the model has to call the tool again for every further fragment.
    That drift shipped once; this locks the two surfaces together.
    """
    import inspect

    from docsift.cli.main import search as cli_search

    cli_defaults = {
        name: param.default.default
        for name, param in inspect.signature(cli_search).parameters.items()
        if hasattr(param.default, "default")
    }

    assert mcp_server.DEFAULT_LIMIT == cli_defaults["limit"]
    assert mcp_server.DEFAULT_MAX_TOKENS == cli_defaults["max_tokens"]
    assert mcp_server.DEFAULT_CONTEXT == cli_defaults["context"]


def test_tool_descriptions_steer_an_agent_towards_search():
    assert "search_document" in mcp_server.CONVERT_DESCRIPTION
    assert "context window" in mcp_server.SEARCH_DESCRIPTION


def test_server_exposes_both_tools():
    pytest.importorskip("mcp", reason="needs the mcp extra")
    import asyncio

    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert {"search_document", "convert_document"} <= names


def test_advertised_tools_describe_their_arguments():
    """A model picks arguments from the schema, so it has to be populated."""
    pytest.importorskip("mcp", reason="needs the mcp extra")
    import asyncio

    tools = asyncio.run(mcp_server.build_server().list_tools())
    search = next(tool for tool in tools if tool.name == "search_document")
    properties = search.input_schema["properties"]

    assert {"path", "query"} <= set(properties)
    assert set(search.input_schema.get("required", [])) == {"path", "query"}


def test_missing_sdk_gives_an_install_hint_not_a_traceback(monkeypatch):
    """Importing docsift.mcp_server succeeds without the SDK, so the CLI has to
    check explicitly -- otherwise the failure surfaces from inside the server
    start as a raw ImportError."""
    from typer.testing import CliRunner

    from docsift.cli.main import app

    monkeypatch.setattr(mcp_server, "sdk_available", lambda: False)
    result = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"}).invoke(app, ["mcp"])

    assert result.exit_code == 1
    assert "pip install 'docsift[mcp]'" in result.output
    assert "Traceback" not in result.output
