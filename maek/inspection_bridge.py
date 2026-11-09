"""Local RGB bridge: run MAEK's existing rust baseline on actual camera pixels.

The detector never receives scene defect labels, expected answers, or pipe geometry.
RGB evidence is not a crack probability or a future failure prediction.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from PIL import Image

from maek.camera.segment import segment_rust

MODEL = "maek.camera.segment.segment_rust / HSV baseline"
MAX_BYTES = 8_000_000


def regions(mask: np.ndarray, minimum: int = 30) -> list[dict]:
    """Connected pixels with representative *inside-mask* samples, top-left origin."""
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        seen[y, x] = True
        queue = deque([(int(y), int(x))])
        pixels = []
        while queue:
            py, px = queue.popleft()
            pixels.append((py, px))
            for ny, nx in ((py - 1, px), (py + 1, px), (py, px - 1), (py, px + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        if len(pixels) < minimum:
            continue
        p = np.asarray(pixels)
        samples = p[np.linspace(0, len(p) - 1, min(64, len(p)), dtype=int)]
        found.append({
            "kind": "surface_corrosion_candidate", "pixelCount": len(p),
            "bbox": [int(p[:, 1].min()), int(p[:, 0].min()),
                     int(p[:, 1].max()) + 1, int(p[:, 0].max()) + 1],
            "samples": [{"u": (int(px) + 0.5) / width, "v": (int(py) + 0.5) / height}
                        for py, px in samples],
        })
    return sorted(found, key=lambda c: -c["pixelCount"])[:32]


def analyse(payload: dict) -> dict:
    request_id = payload.get("requestId", "")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
        raise ValueError("requestId is required (1..100 characters)")
    raw = base64.b64decode(payload["imageBase64"], validate=True)
    if len(raw) > MAX_BYTES:
        raise ValueError("Image exceeds size limit")
    with Image.open(io.BytesIO(raw)) as source:
        if source.width > 1280 or source.height > 720:
            raise ValueError("Capture must be at most 1280x720")
        rgb = np.asarray(source.convert("RGB"))
    mask = segment_rust(rgb)
    components = regions(mask)
    return {
        "version": 1, "requestId": request_id, "status": "ok", "model": MODEL,
        "imageSha256": hashlib.sha256(raw).hexdigest(),
        "width": rgb.shape[1], "height": rgb.shape[0], "components": components,
        "scope": "Synthetic scene RGB; uncalibrated rust colour baseline; not crack prediction",
        "negativeMeaning": "No RGB candidate is not proof of pipe integrity",
    }


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.reply(200, {"status": "ok", "model": MODEL, "version": 1})
        else:
            self.reply(404, {"status": "error", "message": "Unknown endpoint"})

    def do_POST(self) -> None:
        if self.path != "/analyse":
            self.reply(404, {"status": "error", "message": "Unknown endpoint"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BYTES:
                raise ValueError("Invalid request size")
            self.reply(200, analyse(json.loads(self.rfile.read(size))))
        except (ValueError, KeyError, OSError) as exc:
            self.reply(400, {"status": "error", "message": str(exc)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"MAEK RGB bridge on http://127.0.0.1:{args.port}; {MODEL}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
