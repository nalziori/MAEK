"""Serve the MAEK demo site from this folder on 127.0.0.1 and open the browser. Standard library only."""
import functools
import http.server
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "site"
H = http.server.SimpleHTTPRequestHandler
# Windows may map .js to text/plain via the registry; browsers then refuse ES modules.
H.extensions_map.update({".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm",
                         ".json": "application/json", ".onnx": "application/octet-stream", ".woff2": "font/woff2"})


class Quiet(H):
    def log_message(self, *args):
        pass


def main():
    if not (ROOT / "index.html").is_file():
        sys.exit("site folder not found next to serve.py - unzip the whole archive first")
    with socket.socket() as s:  # any free local port
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(ROOT)))
    url = f"http://127.0.0.1:{port}/"
    print(f"MAEK demo: {url}\nKeep this window open. Close it to stop.", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
