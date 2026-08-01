"""Download benchmark corpus PDFs listed in benchmarks/manifest.json.

Run: uv run python scripts/fetch_benchmarks.py
Files land in benchmarks/corpus/ (git-ignored). Failures are reported, not fatal.
"""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "benchmarks" / "manifest.json"
CORPUS = ROOT / "benchmarks" / "corpus"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    CORPUS.mkdir(parents=True, exist_ok=True)
    for doc in manifest["documents"]:
        target = CORPUS / f"{doc['id']}.pdf"
        if target.exists():
            print(f"exists: {target.name}")
            continue
        try:
            urllib.request.urlretrieve(doc["url"], target)
            print(f"fetched: {target.name}")
        except OSError as exc:
            print(f"FAILED {doc['id']}: {type(exc).__name__}")


if __name__ == "__main__":
    main()
