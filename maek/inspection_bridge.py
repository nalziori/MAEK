"""Local RGB bridge: run MAEK's existing rust baseline on actual camera pixels.

The detector never receives scene defect labels, expected answers, or pipe geometry.
RGB evidence is not a crack probability or a future failure prediction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import numpy as np

from maek.camera.segment import segment_rust
from maek.inspection_dashboard import (
    APIError,
    DashboardState,
    bounded_json,
    decode_image,
    metadata,
)

MODEL = "maek.camera.segment.segment_rust / HSV baseline"
MAX_BYTES = 8_000_000
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".gif": "image/gif", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".webp": "image/webp", ".avif": "image/avif",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
}


def default_dashboard_root():
    module = Path(__file__).resolve()
    for root in (module.parent.parent / "dashboard", module.parent / "dashboard"):
        if root.is_dir():
            return root
    return None


def static_file(root: Path, relative: str) -> Path:
    # Decode before checking segments; reject Windows aliases and encoded separators too.
    relative = unquote(relative, errors="strict")
    if not relative or any(c in relative for c in ("%", "\\", ":", "\x00")):
        raise APIError("허용되지 않은 정적 파일 경로입니다", 404)
    parts = relative.split("/")
    if any(not part or part.startswith(".") or part.endswith((".", " ")) for part in parts):
        raise APIError("허용되지 않은 정적 파일 경로입니다", 404)
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise APIError("정적 파일 경로 이탈입니다", 404)
    resolved_parts = candidate.relative_to(root).parts
    if any(part.startswith(".") for part in resolved_parts):
        raise APIError("숨김 파일은 제공하지 않습니다", 404)
    if candidate.suffix.lower() not in STATIC_TYPES or not candidate.is_file():
        raise APIError("정적 파일이 없습니다", 404)
    for path in [candidate, *candidate.parents]:
        if path == root:
            break
        if getattr(path.stat(), "st_file_attributes", 0) & 2:
            raise APIError("숨김 파일은 제공하지 않습니다", 404)
    return candidate


def inject_adapter(body: bytes) -> bytes:
    html = body.decode("utf-8-sig")
    css = Path(__file__).parent / "web" / "existing-dashboard-adapter.css"
    if css.is_file():
        link = "<link rel='stylesheet' href='/api/existing-dashboard-adapter.css'>"
        html, count = re.subn(r"</head\s*>", lambda match: link + match[0], html, count=1, flags=re.IGNORECASE)
        if not count:
            html = link + html
    script = "<script src='/api/existing-dashboard-adapter.js' defer></script>"
    html, count = re.subn(r"</body\s*>", lambda match: script + match[0], html, count=1, flags=re.IGNORECASE)
    if not count:
        html += script
    return html.encode("utf-8")


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
    raw, image = decode_image(payload.get("imageBase64"))
    rgb = np.asarray(image)
    luminance = rgb @ np.array([0.2126, 0.7152, 0.0722])
    mean = float(luminance.mean())
    low_light = mean < 8 and float(np.percentile(luminance, 95)) < 18
    components = [] if low_light else regions(segment_rust(rgb))
    return {
        "version": 1, "requestId": request_id,
        "status": "low_light" if low_light else "ok", "model": MODEL,
        "quality": {"canInfer": not low_light,
                    "code": "low_light" if low_light else "ok", "meanLuminance": mean},
        "imageSha256": hashlib.sha256(raw).hexdigest(),
        "width": rgb.shape[1], "height": rgb.shape[0], "components": components,
        "scope": "Synthetic scene RGB; uncalibrated rust colour baseline; not crack prediction",
        "negativeMeaning": "No RGB candidate is not proof of pipe integrity",
    }


class Handler(BaseHTTPRequestHandler):
    @property
    def dashboard(self) -> DashboardState:
        # Each HTTP server owns independent state, including in local HTTP tests.
        return self.server.dashboard

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def reply(self, status: int, data: dict) -> None:
        self.send_bytes(status, json.dumps(data, allow_nan=False).encode("utf-8"),
                        "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = urlsplit(self.path)
        try:
            if path.path == "/health":
                self.reply(200, {"status": "ok", "model": MODEL, "version": 1,
                                 "capabilities": ["dashboard_v1", "scenarios_v1"]})
            elif path.path == "/api/state":
                self.reply(200, self.dashboard.snapshot())
            elif path.path.startswith("/api/frame/"):
                self.send_bytes(200, self.dashboard.frame(path.path.removeprefix("/api/frame/")),
                                "image/png")
            elif path.path == "/api/control":
                query = parse_qs(path.query)
                self.reply(200, self.dashboard.drain(query.get("sessionId", [None])[0]))
            elif path.path in ("/api/existing-dashboard-adapter.js", "/api/existing-dashboard-adapter.css"):
                asset = static_file(Path(__file__).parent / "web", path.path.rsplit("/", 1)[1])
                self.send_bytes(200, asset.read_bytes(), STATIC_TYPES[asset.suffix.lower()])
            elif path.path.startswith("/api/"):
                raise APIError("알 수 없는 경로입니다", 404)
            else:
                self.serve_dashboard(path.path)
        except (ValueError, OSError, RuntimeError) as exc:
            self.reply(getattr(exc, "status", 400), {"status": "error", "message": str(exc)})

    def serve_dashboard(self, path: str) -> None:
        entry = path in ("/", "/dashboard", "/dashboard/", "/index.html")
        root = self.server.dashboard_root
        if root is None or not root.is_dir():
            raise APIError("기존 MAEK/dashboard 경로가 없습니다. --dashboard-root로 기존 대시보드 폴더를 지정하세요.", 503)
        relative = "index.html" if entry else path.removeprefix("/dashboard/").removeprefix("/")
        asset = static_file(root, relative)
        body = asset.read_bytes()
        if entry:
            body = inject_adapter(body)
        self.send_bytes(200, body, STATIC_TYPES[asset.suffix.lower()])

    def do_POST(self) -> None:
        try:
            endpoints = {"/analyse", "/api/telemetry", "/api/control", "/api/ack", "/api/evaluation"}
            if self.path not in endpoints:
                raise APIError("알 수 없는 경로입니다", 404)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BYTES:
                raise APIError("Invalid request size")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise APIError("JSON 객체가 필요합니다")
            if self.path == "/analyse":
                bounded_json({k: v for k, v in payload.items() if k != "imageBase64"})
                meta = metadata(payload)
                result = analyse(payload)
                raw, image = decode_image(payload.get("imageBase64"))
                # Store PNG bytes unchanged; legacy non-PNG inference still works.
                if image.format == "PNG" or raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    self.dashboard.record_analysis(result, raw, meta)
            elif self.path == "/api/telemetry":
                result = self.dashboard.telemetry_update(payload)
            elif self.path == "/api/control":
                result = self.dashboard.control(payload)
            elif self.path == "/api/ack":
                result = self.dashboard.ack(payload)
            else:
                result = self.dashboard.evaluation(payload)
            self.reply(200, result)
        except (ValueError, KeyError, OSError, RecursionError) as exc:
            self.reply(getattr(exc, "status", 400), {"status": "error", "message": str(exc)})


class InspectionServer(ThreadingHTTPServer):
    def __init__(self, address, handler=Handler, *, dashboard=None, dashboard_root=None):
        if address[0] != "127.0.0.1":
            raise ValueError("Inspection bridge must bind to 127.0.0.1")
        self.dashboard = dashboard if dashboard is not None else DashboardState()
        self.dashboard_root = Path(dashboard_root).resolve() if dashboard_root is not None else default_dashboard_root()
        super().__init__(address, handler)


BridgeServer = InspectionServer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dashboard-root", type=Path, default=None)
    args = parser.parse_args()
    server = BridgeServer(("127.0.0.1", args.port), dashboard_root=args.dashboard_root)
    print(f"MAEK RGB bridge on http://127.0.0.1:{args.port}; {MODEL}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
