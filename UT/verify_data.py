"""Verify the separate large-data inventory without requiring torch or numpy."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    manifest = json.loads((ROOT / "data_manifest.json").read_text(encoding="utf-8"))
    total = 0
    for name, record in manifest.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f"Missing data file: {name}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        if path.stat().st_size != record["bytes"] or digest.hexdigest() != record["sha256"]:
            raise ValueError(f"Data checksum mismatch: {name}")
        total += record["bytes"]
    print(json.dumps({"passed": True, "files": len(manifest), "bytes": total}))


if __name__ == "__main__":
    main()
