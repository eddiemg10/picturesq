"""Download CC0 sample RAWs listed in reference/samples.json, verifying SHA-256.

Usage: uv run python scripts/fetch_samples.py [--dest reference/samples]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=ROOT / "reference" / "samples")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "reference" / "samples.json").read_text())
    args.dest.mkdir(parents=True, exist_ok=True)
    failures = 0
    for sample in manifest["samples"]:
        target = args.dest / sample["name"]
        if target.exists() and sha256(target) == sample["sha256"]:
            print(f"ok      {sample['name']}")
            continue
        print(f"fetch   {sample['name']}")
        urllib.request.urlretrieve(sample["url"], target)
        if sha256(target) != sample["sha256"]:
            print(f"MISMATCH {sample['name']} (checksum differs)", file=sys.stderr)
            target.unlink()
            failures += 1
    if not manifest["samples"]:
        print("No samples listed yet in reference/samples.json.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
