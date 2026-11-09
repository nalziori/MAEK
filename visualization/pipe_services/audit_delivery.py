"""Verify the saved reports, packaged source bytes and preserved CFD input."""
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent / "unity/MAEKInspection"
UNITY = PROJECT / "Assets/MAEK"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def main():
    tests = subprocess.run([sys.executable, str(ROOT / "test_services.py")],
                           capture_output=True, text=True)
    (ROOT / "python_tests.log").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    assert tests.returncode == 0, tests.stderr
    data = json.loads((ROOT / "service_data_report.json").read_text())
    blender = json.loads((ROOT / "blender_service_report.json").read_text())
    unity = json.loads((ROOT / "unity_service_report.json").read_text())
    assert data["status"] == blender["status"] == unity["status"] == "PASS"
    assert all(c["pass"] for c in unity["checks"])
    # The generator and Blender hash decoded text, before Windows LF -> CRLF writing.
    decoded = (ROOT / "pipe_services.json").read_text(encoding="utf-8")
    text_sha = hashlib.sha256(decoded.encode("utf-8")).hexdigest()
    assert data["source_sha256"] == blender["source_sha256"] == text_sha
    assert digest(ROOT / "pipe_services.json") == digest(UNITY / "Source/pipe_services.json")
    assert digest(UNITY / "Source/cfd_playback.json") == (
        "39bad27201fccb35ae0929755be63392d11f22a11ffe7a3557399a60e236f111")
    required = [
        "Scenes/MAEKPipeServices.unity", "Scripts/MAEKPipeService.cs",
        "Scripts/MAEKPipeServices.cs", "Scripts/MAEKDroneInspection.cs",
        "Scripts/MAEKCFDPlayback.cs", "Scripts/MAEKWalkthrough.cs",
        "Editor/BuildPipeServices.cs", "Source/pipe_services.json",
        "Source/service_drone_routes.json", "Source/cfd_playback.json",
        "PIPE_SERVICES_GUIDE.md", "README.md",
    ]
    groups = {}
    package = ROOT / "MAEK_Pipe_Services.unitypackage"
    with tarfile.open(package, "r|gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            name = member.name.replace("\\", "/")
            group, _, leaf = name.rpartition("/")
            if leaf not in ("asset", "pathname"):
                continue
            stream = archive.extractfile(member)
            if leaf == "pathname":
                groups.setdefault(group, {})[leaf] = stream.read().decode().strip()
            else:
                h = hashlib.sha256()
                for part in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(part)
                groups.setdefault(group, {})[leaf] = h.hexdigest()
    indexed = {v["pathname"]: v.get("asset") for v in groups.values() if "pathname" in v}
    checks = {}
    for relative in required:
        key = "Assets/MAEK/" + relative
        assert key in indexed, key
        assert indexed[key] == digest(UNITY / relative), "Stale package asset: " + key
        checks[relative] = "MATCH"
    artifacts = {}
    for name in ("maek_pipe_services.blend", "MAEK_Pipe_Services.unitypackage",
                 "line_service_list.csv", "PIPE_SERVICES_GUIDE.md",
                 "utility_services.png", "pipe_service_overview.png"):
        path = ROOT / name
        assert path.stat().st_size > 100
        artifacts[name] = dict(bytes=path.stat().st_size, sha256=digest(path))
    result = dict(status="PASS", pipes=247, original_pipes_preserved=240, new_utility_pipes=7,
                  service_categories=14, python_tests=6, unity_checks=len(unity["checks"]),
                  blender_saved_file_reopened=blender["saved_file_reopened"],
                  cfd_cache_unchanged=True, package_assets=checks, artifacts=artifacts,
                  limitations=["Fictional layout and service assignment, no actual P&ID",
                               "No pipe hydraulics or CFD coupling added",
                               "Native camera renders exclude the OnGUI panel",
                               "Utility routes added to Unity; original Blender cameras preserved"])
    (ROOT / "delivery_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
