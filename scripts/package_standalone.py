"""Package only a verified self-contained MAEK Windows distribution."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(release: Path) -> dict:
    folder = release / "dist/MAEK"
    test = read(folder / "standalone_verification.json")
    assert test["status"] == "PASS" and test["pipes"] == 247 and test["captures"] == 771
    assert test["supplementaryPipes"] == 17 and test["supplementaryCaptures"] == 17
    assert test["supplementaryFindings"] > 0 and test["recordedFrames"] >= 24
    assert test["maxMovementStep"] <= 1.201 and test["supplementaryMaxMovementStep"] <= 1.201
    bridge = read(release / "frozen_bridge_test.json")
    lifecycle = read(release / "native_lifecycle_test.json")
    assert lifecycle["status"] == "PASS" and lifecycle["ownedServerClosed"]
    for name, expected in lifecycle["testedPlayerFiles"].items():
        assert sha(folder / "Player" / name) == expected, f"Player changed after native test: {name}"
    assert bridge["status"] == "PASS" and bridge["bridgeExeSHA256"] == sha(folder / "MAEK.exe")
    collisions = read(ROOT / "visualization/supplementary_circuits/connections_colliders.json")
    assert collisions["status"] == "PASS" and all(c["pass"] for c in collisions["checks"])
    for name in ["MAEK.exe", "_internal/python313.dll", "Player/MAEK_Player.exe",
                 "Player/UnityPlayer.dll", "Player/MAEK_Player_Data/globalgamemanagers"]:
        assert (folder / name).is_file(), name
    references = ROOT / "docs/references/oxygen-sinter/2026-11-09"
    reference_text = (references / "README.md").read_text(encoding="utf-8")
    reference_text = reference_text.replace("[증설·배포 검토](../../../reviews/oxygen-sinter-delivery-20261109.md)", "[패키지 실행 검증](verification_summary.json)")
    reference_text = reference_text.replace("`sources.json`", "`reference_sources.json`")
    (folder / "REFERENCES.md").write_text("원문 PDF와 외부 사진은 이 실행 패키지에 포함되지 않습니다. 아래 원문 URL로 확인할 수 있습니다.\n\n" + reference_text, encoding="utf-8")
    shutil.copy2(references / "sources.json", folder / "reference_sources.json")
    (folder / "verification_summary.json").write_text(json.dumps({
        "nativePlayer": test, "frozenBridge": bridge,
        "supplementaryGeometry": {k: collisions[k] for k in ("status", "lines", "joints", "colliders", "routeSegments", "views")},
        "supplementaryChecks": len(collisions["checks"]),
        "scope": "Synthetic reference layout and sampled RGB baseline; not field engineering certification",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    files = [p for p in folder.rglob("*") if p.is_file()
             and p.name not in {"standalone_verification.json", "files.sha256.json"}
             and not any("BackUpThisFolder" in s for s in p.parts)]
    manifest = {p.relative_to(folder).as_posix(): sha(p) for p in files}
    (folder / "files.sha256.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    files.append(folder / "files.sha256.json")
    archive = release / "MAEK_Windows_Oxygen_Sinter_20261109.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            z.write(p, "MAEK/" + p.relative_to(folder).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name, expected in manifest.items():
            assert hashlib.sha256(z.read("MAEK/" + name)).hexdigest() == expected, name
    report = {"status": "PASS", "entryPoint": "MAEK/MAEK.exe", "requiresUnityInstallation": False,
              "requiresPythonInstallation": False, "files": len(files), "archive": str(archive),
              "archiveBytes": archive.stat().st_size, "archiveSHA256": sha(archive),
              "playerSHA256": sha(folder / "Player/MAEK_Player.exe"), "nativeTest": test}
    (release / "delivery_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(package(Path(sys.argv[1]).resolve()), ensure_ascii=False, indent=2))
