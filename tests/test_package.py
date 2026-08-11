import re

from docsift import __version__


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.\w+)?", __version__)


def test_server_json_matches_the_package_version():
    """The MCP Registry listing points at a PyPI version; it must be this one."""
    import json
    from pathlib import Path

    from docsift import __version__

    manifest = json.loads((Path(__file__).parents[1] / "server.json").read_text())
    assert manifest["version"] == __version__
    assert manifest["packages"][0]["version"] == __version__
    assert manifest["packages"][0]["identifier"] == "docsift"


def test_readme_carries_the_registry_ownership_marker():
    """The registry verifies this line against the README published on PyPI."""
    from pathlib import Path

    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "mcp-name: io.github.anishmoncivarghese/docsift" in readme
