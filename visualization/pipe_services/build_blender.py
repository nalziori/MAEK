"""Annotate the existing steelworks and add the shared utility demonstration geometry."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
payload = (ROOT/"pipe_services.json").read_text(encoding="utf-8")
data = json.loads(payload)
bpy.ops.wm.open_mainfile(filepath=str(ROOT.parent/"cfd/maek_furnace_cfd.blend"))
scene = bpy.context.scene
# Restore exterior by switching preserved collections, not by replacing the CFD model.
for col in scene.collection.children:
    hidden = col.name.startswith(("00_", "07_", "13_", "14_", "15_"))
    col.hide_render = hidden
    col.hide_viewport = hidden
collection = bpy.data.collections.new("16_Pipe_services_and_utilities")
scene.collection.children.link(collection)
services = {d["code"]: d for d in data["services"]}
lines = {p["id"]: p for p in data["pipes"]}
scene["pipe_service_colors"] = 1.0
scene.id_properties_ui("pipe_service_colors").update(min=0, max=1)
scene["pipe_service_basis"] = data["basis"]
scene["pipe_service_source_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
originals, materials = {}, {}


def material(key, color):
    m = bpy.data.materials.new(key)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    p = m.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Metallic"].default_value = .45
    p.inputs["Roughness"].default_value = .4
    return m


def shape(name, kind, pos, size, mat):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    if kind == "box":
        bmesh.ops.create_cube(bm, size=1)
    elif kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=32,
                             radius1=.5, radius2=.5, depth=1)
    else:
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=.5)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    collection.objects.link(ob)
    ob.location = pos
    ob.scale = size
    return ob


for asset in data["utilityAssets"]:
    ob = shape(asset["id"], asset["shape"], asset["position"], asset["size"],
               material("UTILITY "+asset["id"], asset["color"]))
    ob["asset_id"] = asset["id"]
    ob["purpose"] = asset["label"]
    ob["mount_on"] = asset["mountOn"]

for pipe in data["pipes"]:
    if not pipe["newGeometry"]:
        continue
    cu = bpy.data.curves.new(pipe["id"], "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = pipe["radius"]
    cu.bevel_resolution = 3
    cu.use_fill_caps = True
    spline = cu.splines.new("POLY")
    spline.points.add(len(pipe["points"])-1)
    for point, p in zip(spline.points, pipe["points"]):
        point.co = (*p["position"], 1)
    mat = material("UTILITY PIPE "+pipe["id"], [.36, .39, .41])
    cu.materials.append(mat)
    ob = bpy.data.objects.new(pipe["id"], cu)
    collection.objects.link(ob)
    ob["line_id"] = pipe["id"]
    for j, p in enumerate(pipe["points"][1:-1]):
        fitting = shape(pipe["id"]+" elbow "+str(j), "sphere", p["position"],
                        [pipe["radius"]*2]*3, mat)
        fitting["line_id"] = pipe["id"]


def tint(original, code):
    key = (original.name, code)
    if key in materials:
        return materials[key]
    m = original.copy()
    m.name = "SERVICE "+code+" | "+original.name
    color = services[code]["color"]
    m.diffuse_color = (*color, 1)
    if m.use_nodes:
        p = m.node_tree.nodes.get("Principled BSDF")
        if p:
            base = p.inputs["Base Color"]
            old_color = tuple(base.default_value)
            upstream = base.links[0].from_socket if base.is_linked else None
            for link in list(base.links):
                m.node_tree.links.remove(link)
            mix = m.node_tree.nodes.new("ShaderNodeMixRGB")
            mix.blend_type = "MIX"
            mix.inputs[1].default_value = old_color
            mix.inputs[2].default_value = (*color, 1)
            if upstream:
                m.node_tree.links.new(upstream, mix.inputs[1])
            m.node_tree.links.new(mix.outputs[0], base)
            driver = mix.inputs[0].driver_add("default_value").driver
            variable = driver.variables.new()
            variable.name = "mode"
            variable.type = "SINGLE_PROP"
            variable.targets[0].id_type = "SCENE"
            variable.targets[0].id = scene
            variable.targets[0].data_path = '["pipe_service_colors"]'
            driver.expression = ".7 * mode"
    materials[key] = m
    return m


bound = set()
object_count = 0
for ob in scene.objects:
    key = ob.get("line_id") or ob.name.split(" ")[0]
    if key not in lines or ob.type not in ("MESH", "CURVE"):
        continue
    pipe = lines[key]
    definition = services[pipe["serviceCode"]]
    for prop, value in {"line_id": key, "service_code": pipe["serviceCode"],
                        "fluid": pipe["medium"], "purpose_ko": definition["purpose"],
                        "from_node": pipe["fromNode"], "to_node": pipe["toNode"],
                        "normal_state": pipe["state"], "flow_basis": pipe["flowBasis"],
                        "inspection_context": definition["inspection"]}.items():
        ob[prop] = value
    originals[ob.name] = [m.name for m in ob.data.materials]
    # Data can be shared by fittings: keep each service's material assignments local.
    ob.data = ob.data.copy()
    for i, m in enumerate(ob.data.materials):
        ob.data.materials[i] = tint(m, pipe["serviceCode"])
    bound.add(key)
    object_count += 1
assert bound == set(lines), sorted(set(lines)-bound)
guide = ROOT/"PIPE_SERVICES_GUIDE.md"
if guide.exists():
    bpy.data.texts.new("READ_ME_PIPE_SERVICES").write(guide.read_text(encoding="utf-8"))
bpy.data.texts.new("PIPE_SERVICES.json").write(payload)
bpy.data.texts.new("PIPE_ORIGINAL_MATERIALS.json").write(json.dumps(originals, indent=1))
scene.frame_set(289)
camera = scene.camera
camera.location = (-125, 110, 85)
camera.rotation_euler = (Vector((-60, 15, 20))-camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 30
target = ROOT/"maek_pipe_services.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(target))
print("SERVICE_BLEND_SAVED", len(bound), object_count, flush=True)
# Reopen to check actual serialization and the preserved CFD cache.
bpy.ops.wm.open_mainfile(filepath=str(target))
saved = json.loads(bpy.data.texts["PIPE_SERVICES.json"].as_string())
assert len(saved["pipes"]) == 247
assert bpy.data.texts.get("CFD_COMPUTED_FIELDS.json.zlib.base64") is not None
assert not bpy.data.collections["12_Original_shells__toggle_for_exterior"].hide_viewport
assert bpy.data.collections["15_3D_CFD_computed_fields"].hide_viewport
for pipe in saved["pipes"]:
    assert bpy.data.objects[pipe["id"]]["service_code"] == pipe["serviceCode"]
report = dict(status="PASS", pipe_count=len(bound), annotated_objects=object_count,
              cfd_cache_preserved=True, source_sha256=hashlib.sha256(payload.encode()).hexdigest(),
              saved_file_reopened=True, original_shapes_preserved=True)
(ROOT/"blender_service_report.json").write_text(json.dumps(report, indent=2))
print("SERVICE_BLEND_VERIFIED", json.dumps(report), flush=True)
