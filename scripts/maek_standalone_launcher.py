"""Launch the bundled local RGB bridge and Unity player; no Python installation required."""
from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def main():
    if "--bridge" in sys.argv:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - process-lifetime stream
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 - process-lifetime stream
        sys.argv.remove("--bridge")
        from maek.inspection_bridge import main as bridge_main
        bridge_main()
        return 0
    home = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    logs = Path(os.environ.get("LOCALAPPDATA", str(home))) / "MAEKStandalone" / time.strftime("%Y%m%d-%H%M%S")
    logs.mkdir(parents=True, exist_ok=True)
    verify = "--verify" in sys.argv
    player = home / "Player" / "MAEK_Player.exe"
    if not player.exists():
        raise FileNotFoundError("Player/MAEK_Player.exe is missing. Extract the entire ZIP before starting.")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(Path(__file__).resolve())]
    with (logs / "analysis.log").open("w", encoding="utf-8") as output:
        server = subprocess.Popen(cmd + ["--bridge", "--port", str(port)], stdout=output,
                                  stderr=output, stdin=subprocess.DEVNULL, env=env,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(120):
                if server.poll() is not None:
                    raise RuntimeError("Analysis service stopped. See " + str(logs))
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as reply:
                        health = json.load(reply)
                    if health.get("status") == "ok" and health.get("model") == "maek.camera.segment.segment_rust / HSV baseline":
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.25)
            else:
                raise TimeoutError("Analysis service startup timed out. See " + str(logs))
            args = [str(player), "-screen-fullscreen", "0", "-screen-width", "1280", "-screen-height", "720",
                    "-maek-endpoint", f"http://127.0.0.1:{port}/analyse", "-logFile", str(logs / "player.log")]
            if verify:
                args += ["-batchmode", "-maek-verify", "-maek-report", str(home / "standalone_verification.json")]
            process = subprocess.Popen(args, cwd=str(player.parent), env=env,
                                       startupinfo=None)
            code = process.wait()
            (logs / "launcher.json").write_text(json.dumps({"exitCode": code, "port": port,
                "analysisOwnedPid": server.pid, "verify": verify}), encoding="utf-8")
            return code
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - top-level GUI error boundary
        ctypes.windll.user32.MessageBoxW(0, str(error), "MAEK startup error", 0x10)
        raise SystemExit(1)
