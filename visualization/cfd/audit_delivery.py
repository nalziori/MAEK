"""Check delivered cache hashes, package bytes, reports and source archive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

from PIL import Image, ImageStat

from export_results import load

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent/"unity/MAEKInspection"
reports = {name: json.loads((ROOT/name).read_text()) for name in (
    "verification.json", "unity_cfd_report.json", "blender_cfd_report.json",
    "saved_blender_verification.json")}
assert all(r["status"] == "PASS" for r in reports.values())
assert "CFD_SCENE_COMPLETE" in (ROOT/"unity_build.log").read_text(errors="replace")
assert "Ran 7 tests" in (ROOT/"numerical_tests.log").read_text()
assert "\nOK" in (ROOT/"numerical_tests.log").read_text()
digest = hashlib.sha256((ROOT/"cfd_playback.json").read_bytes()).hexdigest()
assert digest == reports["verification.json"]["playback_sha256"]
assert digest == reports["saved_blender_verification.json"]["source_sha256"]
for case in ("hearth", "hearth_fine", "hearth_equilibrium"):
    load(ROOT/case)  # Also rejects stale time directories and reordered cells.
required = [
    "Assets/MAEK/Scenes/MAEKFurnaceCFD.unity",
    "Assets/MAEK/Scripts/MAEKCFDPlayback.cs",
    "Assets/MAEK/Editor/BuildCFDScene.cs",
    "Assets/MAEK/Shaders/CFDField.shader",
    "Assets/MAEK/Shaders/CFDSurface.shader",
    "Assets/MAEK/Source/cfd_playback.json",
    "Assets/MAEK/CFD_GUIDE.md",
    "Assets/MAEK/README.md",
]
with tarfile.open(ROOT/"MAEK_Furnace_CFD.unitypackage", "r:gz") as package:
    paths = {}
    for member in package.getmembers():
        if member.name.endswith("/pathname"):
            path = package.extractfile(member).read().decode().strip()
            paths[path] = member.name.rsplit("/", 1)[0]+"/asset"
    for path in required:
        assert path in paths, path
        assert package.extractfile(paths[path]).read() == (PROJECT/path).read_bytes(), path
for name in ("blender_cfd_hearth.png", "blender_cfd_shaft.png",
             "unity_cfd_hearth.png", "unity_cfd_shaft.png"):
    image = Image.open(ROOT/name).convert("RGB")
    assert image.width >= 1000 and max(ImageStat.Stat(image).stddev) > 20, name
files = [p for p in ROOT.iterdir() if p.is_file() and (
    p.suffix in {".py", ".ps1", ".md", ".txt", ".json"} or
    p.name in {"numerical_tests.log", "export.log"})]
files += [p for name in ("hearth", "hearth_fine", "hearth_equilibrium")
          for p in (ROOT/name).rglob("*") if p.is_file()]
with zipfile.ZipFile(ROOT/"CFD_Source_and_Results.zip", "w", zipfile.ZIP_DEFLATED,
                     compresslevel=4) as archive:
    for path in files:
        archive.write(path, Path("cfd")/path.relative_to(ROOT))
with zipfile.ZipFile(ROOT/"CFD_Source_and_Results.zip") as archive:
    assert archive.testzip() is None
    for name in ("build_blender.py", "export_results.py", "verify_saved_blender.py"):
        assert archive.read("cfd/"+name) == (ROOT/name).read_bytes()
summary = {
    "status": "PASS", "numerical_tests": 7,
    "cfd_checks": len(reports["verification.json"]["checks"]),
    "unity_checks": len(reports["unity_cfd_report.json"]["checks"]),
    "retained_drone_routes": 240, "retained_mesh_colliders": 323,
    "saved_blender_frames_checked": 3, "matched_packaged_assets": len(required),
    "source_archive_files": len(files), "cache_sha256": digest,
    "scope": "3D isothermal VOF hearth; independent 3D reactive Darcy shaft; offline playback.",
    "remaining_limits": "No full-furnace two-way coupling or plant validation; local velocity "
                        "is not grid independent. No resolved taphole or 3D external runner.",
    "artifacts": {name: (ROOT/name).stat().st_size for name in (
        "maek_furnace_cfd.blend", "MAEK_Furnace_CFD.unitypackage",
        "CFD_Source_and_Results.zip", "CFD_GUIDE.md")},
}
(ROOT/"delivery_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
