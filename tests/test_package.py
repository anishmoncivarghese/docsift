import re

from docsift import __version__


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.\w+)?", __version__)
