"""The shared prefab must resolve from a clean checkout without ShiftLink installed."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "unity/MAEKInspection/Assets"
ROOT = ASSETS / "MAEK"
ART = ROOT / "Story/ShiftLinkWorker"
PREFAB = ROOT / "Resources/MAEK/MaintenanceInspector.prefab"


def test_prefab_has_no_missing_local_asset_references():
    guids = {}
    for path in ASSETS.rglob("*.meta"):
        match = re.search(r"^guid: ([a-f0-9]{32})$", path.read_text(encoding="utf-8-sig"), re.MULTILINE)
        if match:
            assert match[1] not in guids, f"Duplicate asset GUID: {path} / {guids[match[1]]}"
            guids[match[1]] = path
    for path in [PREFAB, *ART.glob("Materials/*.mat")]:
        for guid in re.findall(r"guid: ([a-f0-9]{32})", path.read_text(encoding="utf-8-sig")):
            if guid.startswith("0000000000000000"):
                continue  # Unity built-in shader/material references.
            assert guid in guids, f"Missing dependency in {path}: {guid}"
    for name in ["MAEKMaintenanceInspector.cs", "MAEKInspectorVisual.cs"]:
        meta = (ROOT / "Scripts" / (name + ".meta")).read_text(encoding="utf-8")
        guid = re.search(r"guid: (\w+)", meta)[1]
        assert guid in PREFAB.read_text(encoding="utf-8")


def test_source_model_and_palette_are_intact():
    provenance = json.loads((ART / "provenance.json").read_text(encoding="utf-8"))
    for item in provenance["assets"]:
        relative = item["source"].split("ChibiWorkers_v2\\", 1)[1]
        path = ART.joinpath(*relative.split("\\"))
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], path


def test_shared_prefab_has_real_body_and_no_shiftlink_script_dependency():
    text = PREFAB.read_text(encoding="utf-8")
    assert "FactoryWorkerVisual" not in text
    assert "Assembly-CSharp::MAEKInspectorVisual" in text
    assert "Assembly-CSharp::MAEK.MAEKMaintenanceInspector" in text
    assert "CapsuleCollider:" in text and "m_IsTrigger: 0" in text
    assert "m_Height: 1.8" in text and "m_Radius: 0.5" in text
    assert "m_Layer: 8" in text
