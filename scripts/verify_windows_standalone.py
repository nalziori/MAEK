"""Run the delivered launcher/player with no external Python/Unity in PATH."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path


def verify(release: Path) -> dict:
    folder = release / "dist/MAEK"
    assert (folder / "Player/MAEK_Player.exe").is_file()
    env = dict(os.environ)
    env["PATH"] = os.environ["SystemRoot"] + ";" + os.environ["SystemRoot"] + "/System32"
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    started = time.time()
    process = subprocess.Popen([str(folder / "MAEK.exe"), "--verify"], cwd=folder, env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    code = process.wait(timeout=1860)
    assert code == 0, f"Native verification failed: exit {code}"
    report = json.loads((folder / "standalone_verification.json").read_text(encoding="utf-8-sig"))
    assert report["status"] == "PASS" and report["pipes"] == 247 and report["captures"] == 771
    assert report["supplementaryPipes"] == 17 and report["supplementaryCaptures"] == 17
    logs = sorted((Path(os.environ["LOCALAPPDATA"]) / "MAEKStandalone").glob("*/launcher.json"), key=lambda p: p.stat().st_mtime)
    assert logs and logs[-1].stat().st_mtime >= started
    lifecycle = json.loads(logs[-1].read_text(encoding="utf-8"))
    assert lifecycle["exitCode"] == 0 and lifecycle["verify"]
    try:
        with socket.create_connection(("127.0.0.1", lifecycle["port"]), timeout=1):
            raise AssertionError("Owned analysis server remained open after exit")
    except OSError:
        pass
    log = (logs[-1].parent / "player.log").read_text(encoding="utf-8", errors="replace")
    assert not re.search(r"(?:NullReference|MissingReference|InvalidOperation|TypeInitialization|ArgumentNull|ArgumentOutOfRange)Exception", log), "Native runtime exception in player.log"
    assert "MAEK_STANDALONE_PASS" in log
    hashes = {p.relative_to(folder / "Player").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (folder / "Player").rglob("*") if p.is_file() and not any("BackUpThisFolder" in s for s in p.parts)}
    result = {"status": "PASS", "isolatedPATH": env["PATH"], "exitCode": code,
              "ownedServerClosed": True, "logs": str(logs[-1].parent),
              "nativeReport": report, "testedPlayerFiles": hashes}
    (release / "native_lifecycle_test.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (release / "frozen_bridge_test.json").write_text(json.dumps({
        "status": "PASS", "verifiedBy": "native 247+17 RGB capture/response provenance checks",
        "bridgeExeSHA256": hashlib.sha256((folder / "MAEK.exe").read_bytes()).hexdigest(),
        "isolatedPATH": env["PATH"],
    }, indent=2), encoding="utf-8")
    return {k: v for k, v in result.items() if k != "testedPlayerFiles"}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]).resolve()), indent=2))
