"""Download benchmark corpus PDFs listed in benchmarks/manifest.json.

Run: uv run python scripts/fetch_benchmarks.py
Files land in benchmarks/corpus/ (git-ignored). Failures are reported, not fatal.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "benchmarks" / "manifest.json"
CORPUS = ROOT / "benchmarks" / "corpus"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    CORPUS.mkdir(parents=True, exist_ok=True)
    for doc in manifest["documents"]:
        target = CORPUS / f"{doc['id']}.pdf"
        if target.exists():
            print(f"exists: {target.name}")
            continue
        if not doc["url"].startswith("https://"):
            print(f"SKIPPED {doc['id']}: non-https url")
            continue
        try:
            urllib.request.urlretrieve(doc["url"], target)
            print(f"fetched: {target.name}")
        except (OSError, ValueError) as exc:
            print(f"FAILED {doc['id']}: {type(exc).__name__}")
            continue
        expected_sha256 = doc.get("sha256")
        if expected_sha256 and _sha256(target) != expected_sha256:
            target.unlink()
            print(f"FAILED {doc['id']}: sha256 mismatch")


if __name__ == "__main__":
    main()
