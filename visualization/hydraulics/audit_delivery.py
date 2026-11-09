"""Check numerical evidence, persisted artifacts and exact Unity package contents."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VIS = ROOT.parent
UNITY = VIS.parent/"unity/MAEKInspection/Assets/MAEK"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as file:
        for part in iter(lambda: file.read(1024*1024), b""):
            h.update(part)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    for script, log in ((ROOT/"test_hydraulics.py", "numerical_tests.log"),
                        (VIS/"cfd/test_cfd.py", "legacy_cfd_tests.log")):
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        (ROOT/log).write_text(result.stdout+result.stderr, encoding="utf-8")
        assert result.returncode == 0 and "skipped" not in result.stderr, result.stderr
    unity = load(ROOT/"unity_hydraulic_report.json")
    blender = load(ROOT/"blender_hydraulic_report.json")
    hearth = load(ROOT/"hearth_coupling_report.json")
    assert unity["status"] == blender["status"] == hearth["status"] == "PASS"
    assert all(c["pass"] for c in unity["checks"])
    assert blender["pipes"] == 247 and blender["saved_file_reopened"]
    assert all(all(c["checks"].values()) for c in hearth["cases"])
    data = load(ROOT/"hydraulic_results.json")
    assert digest(ROOT/"hydraulic_results.json") == digest(UNITY/"Source/hydraulic_results.json")
    assert digest(UNITY/"Source/cfd_playback.json") == (
        "39bad27201fccb35ae0929755be63392d11f22a11ffe7a3557399a60e236f111")
    for scenario in data["scenarios"]:
        name = scenario["clipName"]
        assert digest(ROOT/name) == digest(UNITY/"Source"/name)
        clip = load(ROOT/name)
        assert len(clip["unitShafts"]) == len(clip["unitHearths"]) == 2
        assert clip["hearthCells"] == 20224
        for unit in clip["unitHearths"]:
            assert unit["frames"][-1]["time"] == 12
        for unit in clip["unitShafts"]:
            assert unit["frames"][-1]["time"] == 30
    required = ["Scenes/MAEKHydraulicCFD.unity", "Scripts/MAEKHydraulicFlow.cs",
                "Scripts/MAEKCFDPlayback.cs", "Scripts/MAEKPipeServices.cs",
                "Scripts/FlowGlyph.shader", "Editor/BuildHydraulicScene.cs",
                "Source/hydraulic_results.json", "HYDRAULIC_CFD_GUIDE.md", "README.md"]
    required.extend("Source/"+s["clipName"] for s in data["scenarios"])
    groups = {}
    with tarfile.open(ROOT/"MAEK_Hydraulic_CFD.unitypackage", "r|gz") as archive:
        for member in archive:
            group, _, leaf = member.name.replace("\\", "/").rpartition("/")
            if not member.isfile() or leaf not in ("asset", "pathname"):
                continue
            stream = archive.extractfile(member)
            if leaf == "pathname":
                value = stream.read().decode().strip()
            else:
                h = hashlib.sha256()
                for part in iter(lambda: stream.read(1024*1024), b""):
                    h.update(part)
                value = h.hexdigest()
            groups.setdefault(group, {})[leaf] = value
    indexed = {v["pathname"]: v.get("asset") for v in groups.values() if "pathname" in v}
    for name in required:
        assert indexed.get("Assets/MAEK/"+name) == digest(UNITY/name), name
    files = {}
    for name in ("maek_hydraulic_cfd.blend", "MAEK_Hydraulic_CFD.unitypackage",
                 "pipe_pressure_flow.csv", "HYDRAULIC_CFD_GUIDE.md",
                 "hydraulic_overview.png", "hydraulic_pipe_detail.png",
                 "coupled_shaft_pressure.png", "coupled_shaft_speed.png"):
        path = ROOT/name
        assert path.stat().st_size > 100
        files[name] = dict(bytes=path.stat().st_size, sha256=digest(path))
    report = dict(status="PASS", pipes=247, services=14, scenarios=3,
                  hydraulic_tests=8, original_cfd_tests=7, unity_checks=len(unity["checks"]),
                  hearth_cases=2, hearth_cells=20224, hearth_duration_s=12,
                  shaft_cells=1496, shaft_duration_s=30, package_assets_matched=len(required),
                  artifacts=files, baseline_cfd_reference_preserved=True,
                  case_summary=[dict(id=s["id"], furnaces=s["furnaces"],
                                     mass_residual_kg_s=s["massResidual"],
                                     pressure_residual_pa=s["pressureResidual"])
                                for s in data["scenarios"]],
                  limitations=["Assumed operating conditions, not plant calibration",
                               "Two-way steady Darcy hydraulics; no reaction-density feedback",
                               "One-way gas pressure/nozzle closure to VOF; fixed initial head",
                               "Precomputed scenarios, not a live OpenFOAM solver in Unity",
                               "Blender baked animation shows the baseline case"])
    (ROOT/"delivery_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in
                      ("artifacts", "case_summary")}, indent=2))


if __name__ == "__main__":
    main()
