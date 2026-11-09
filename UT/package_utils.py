"""Integrity checks for the relocatable UT handoff; no scientific dependencies."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return Path(path).read_text(encoding="utf-8-sig")


def verify_package():
    manifest = json.loads(read_json(ROOT / "manifest.json"))
    for name, digest in manifest.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f"Missing or invalid package file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Package file changed: {name}")
    return len(manifest)


if __name__ == "__main__":
    print(json.dumps({"files_checked": verify_package(), "passed": True}))
