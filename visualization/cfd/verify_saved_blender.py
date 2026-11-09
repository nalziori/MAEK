"""Reopen the delivered Blender file and check the actual stored cache/frames."""
from __future__ import annotations

import hashlib
import base64
import json
import zlib
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
scene = bpy.context.scene
packed = bpy.data.texts["CFD_COMPUTED_FIELDS.json.zlib.base64"].as_string()
payload = zlib.decompress(base64.b64decode(packed)).decode()
expected = hashlib.sha256((ROOT/"cfd_playback.json").read_bytes()).hexdigest()
assert hashlib.sha256(payload.encode()).hexdigest() == expected
assert scene["CFD_source_sha256"] == expected
collection = bpy.data.collections["15_3D_CFD_computed_fields"]
checks = []
for frame in (1, 145, 289):
    scene.frame_set(frame)
    visible = [ob for ob in collection.objects if not ob.hide_render and
               ob.type == "MESH" and len(ob.data.polygons) > 0]
    assert len(visible) == (6 if frame == 1 else 8), (frame, len(visible))
    for ob in visible:
        assert all(mat is not None for mat in ob.data.materials), ob.name
        expected_time = (frame-1)/24 * (10 if "shaft" in ob.name else 1)
        assert f"t={expected_time:g}s" in ob.name, (frame, ob.name)
    checks.append({"frame": frame, "nonempty_visible_meshes": len(visible)})
cut = bpy.data.collections["13_Physics_section_shells"]
assert all(ob.data.materials and all(m is not None for m in ob.data.materials)
           for ob in cut.objects if ob.type == "MESH")
assert scene.frame_start == 1 and scene.frame_end == 289
report = {"status": "PASS", "source_sha256": expected, "saved_state_checks": checks,
          "saved_section_material_objects": len(cut.objects),
          "scope": scene["CFD_scope"]}
(ROOT/"saved_blender_verification.json").write_text(json.dumps(report, indent=2))
print("SAVED_CFD_BLEND_VERIFIED", json.dumps(report), flush=True)
