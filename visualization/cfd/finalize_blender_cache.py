"""Bind generated f-curves to Blender 4.5 slots; reject overlapping time states."""
from __future__ import annotations

import json
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
scene = bpy.context.scene
collection = bpy.data.collections["15_3D_CFD_computed_fields"]
bound = 0
for obj in collection.objects:
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        assert len(action.slots) == 1
        obj.animation_data.action_slot = action.slots[0]
        bound += 1
    if obj.type == "FONT":
        obj.location.y = max(obj.location.y, 19)
checks = []
for frame in (1, 145, 289):
    scene.frame_set(frame)
    visible = [obj for obj in collection.objects if obj.type == "MESH" and not obj.hide_render]
    print("FRAME_VISIBILITY", frame, len(visible), flush=True)
    assert len(visible) == 8, (frame, len(visible))
    checks.append({"frame": frame, "visible_meshes": len(visible), "pass": True})
scene.frame_set(289)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
camera = scene.camera
camera.location = (-48, 43, 16)
camera.rotation_euler = (Vector((-62, 18, 5.8))-camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 38
scene.render.filepath = str(ROOT/"blender_cfd_hearth.png")
bpy.ops.render.render(write_still=True)
camera.location = (-50, 79, 29)
camera.rotation_euler = (Vector((-62, 18, 23))-camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 32
scene.render.filepath = str(ROOT/"blender_cfd_shaft.png")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
bpy.ops.render.render(write_still=True)
(ROOT/"blender_cfd_report.json").write_text(json.dumps({
    "status": "PASS", "checks": checks, "bound_action_slots": bound,
    "source_sha256": scene["CFD_source_sha256"], "objects": len(collection.objects),
    "scope": scene["CFD_scope"]}, indent=2))
print("CFD_SLOT_BINDING_VERIFIED", bound, flush=True)
