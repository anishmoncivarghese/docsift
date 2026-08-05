import tomllib
from pathlib import Path

from docsift import __version__

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_package_version_matches_pyproject():
    """__version__ and pyproject.toml's [project].version are two hardcoded
    strings with nothing else checking they agree -- pin it so a version
    bump that only updates one of them fails CI instead of shipping a
    mismatched build."""
    pyproject = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    assert __version__ == pyproject["project"]["version"]
