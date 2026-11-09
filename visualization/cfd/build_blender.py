"""Build native Blender playback from computed OpenFOAM/shaft fields."""
from __future__ import annotations

import hashlib
import base64
import json
import math
import zlib
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
payload = (ROOT/"cfd_playback.json").read_text()
data = json.loads(payload)
print("CFD_JSON_LOADED", flush=True)
bpy.ops.wm.open_mainfile(filepath=str(ROOT.parent/"maek_furnace_physics.blend"))
print("CFD_SOURCE_BLEND_LOADED", flush=True)
scene = bpy.context.scene
previous = bpy.data.collections.get("14_Calculated_reactions_and_molten_flow")
previous.hide_render = True
previous.hide_viewport = True
for ob in previous.objects:
    if ob.animation_data:
        ob.animation_data_clear()
collection = bpy.data.collections.new("15_3D_CFD_computed_fields")
scene.collection.children.link(collection)
for ob in scene.objects:
    if ob.type == "CAMERA" and ob.animation_data:
        ob.animation_data_clear()


def material(name, color, emission=0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = (*color, 1)
    p = m.node_tree.nodes.get("Principled BSDF")
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Metallic"].default_value = .35
    p.inputs["Roughness"].default_value = .32
    p.inputs["Emission Color"].default_value = (*color, 1)
    p.inputs["Emission Strength"].default_value = emission
    return m


iron = material("CFD iron alpha=0.5", (1, .16, .012), .6)
slag = material("CFD slag alpha=0.5", (.32, .20, .035), .1)
cyan = material("CFD velocity x 2 seconds", (.02, .8, 1), 1)
white = material("CFD legend", (.86, .91, 1), .7)
fieldmat = material("CFD solved shaft temperature", (1, 1, 1))
nt = fieldmat.node_tree
vcol = nt.nodes.new("ShaderNodeVertexColor")
vcol.layer_name = "Temperature"
p = nt.nodes.get("Principled BSDF")
nt.links.new(vcol.outputs["Color"], p.inputs["Base Color"])
nt.links.new(vcol.outputs["Color"], p.inputs["Emission Color"])
p.inputs["Emission Strength"].default_value = .7


def ramp(v):
    t = min(1, max(0, v))
    a, b, w = ((.04, .16, .65), (.1, .9, .7), t*2) if t < .5 else (
        (.1, .9, .7), (1, .12, .025), (t-.5)*2)
    return tuple(a[i]*(1-w)+b[i]*w for i in range(3))+(1,)


def mesh_object(name, vertices, faces, mat):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def visibility(obj, first, last):
    action = bpy.data.actions.new(obj.name+" visibility")
    obj.animation_data_create()
    obj.animation_data.action = action
    states = sorted({1: True, first: False, last+1: True}.items())
    for name in ("hide_render", "hide_viewport"):
        fc = action.fcurves.new(data_path=name)
        fc.keyframe_points.add(len(states))
        for key, (frame, hidden) in zip(fc.keyframe_points, states):
            key.co = (frame, float(hidden))
            key.interpolation = "CONSTANT"
    obj.animation_data.action_slot = action.slots[0]


def surface(name, values, x, mat):
    verts = [(values["vertices"][i]+x, values["vertices"][i+1]+18,
              values["vertices"][i+2]+3.2) for i in range(0, len(values["vertices"]), 3)]
    tri = values["triangles"]
    obj = mesh_object(name, verts, [tri[i:i+3] for i in range(0, len(tri), 3)], mat)
    # Native section cut, while full surfaces remain embedded in the JSON text.
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                          plane_co=(0, 18, 0), plane_no=(0, 1, 0),
                          clear_outer=True, dist=1e-6)
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def label(text, pos, size):
    cu = bpy.data.curves.new(text, "FONT")
    cu.body = text
    cu.size = size
    cu.align_x = "CENTER"
    cu.materials.append(white)
    ob = bpy.data.objects.new(text, cu)
    collection.objects.link(ob)
    ob.location = (pos[0], max(pos[1], 19), pos[2])
    ob.rotation_euler = (math.pi/2, 0, math.pi)
    return ob


for unit, x in enumerate((-62, 62)):
    print("CFD_BUILD_UNIT", unit, flush=True)
    for index, fr in enumerate(data["hearthFrames"]):
        first = 1+round(fr["time"]*24)
        last = first+23 if index < 12 else 289
        for key, mat in (("iron", iron), ("slag", slag)):
            obj = surface(f"BF{unit+1} {key} solved t={fr['time']:g}s", fr[key], x, mat)
            visibility(obj, first, last)
        vs, fs = [], []
        for i in range(len(fr["vectors"])//3):
            p = Vector((x+data["vectorPositions"][3*i], 18.03,
                        3.2+data["vectorPositions"][3*i+2]))
            v = Vector(fr["vectors"][3*i:3*i+3])
            if v.length < 1e-6:
                continue
            end = p+v*10
            side = Vector((v.z, 0, -v.x)).normalized()*.012
            base = end-v.normalized()*min(.08, v.length*3)
            k = len(vs)
            vs.extend([p-side, p+side, base+side, base-side,
                       base-side*3, base+side*3, end])
            fs.extend([(k, k+1, k+2, k+3), (k+4, k+5, k+6)])
        obj = mesh_object(f"BF{unit+1} velocity t={fr['time']:g}s", vs, fs, cyan)
        visibility(obj, first, last)
    for index, fr in enumerate(data["shaftFrames"]):
        vs, fs, colors = [], [], []
        for i in range(len(data["shaftPositions"])//3):
            px, py, pz = data["shaftPositions"][3*i:3*i+3]
            if abs(py-.5) > .01:
                continue
            k = len(vs)
            vs.extend([(x+px-.49, 18.5, 7.2+pz-.49), (x+px+.49, 18.5, 7.2+pz-.49),
                       (x+px+.49, 18.5, 7.2+pz+.49), (x+px-.49, 18.5, 7.2+pz+.49)])
            fs.append((k, k+1, k+2, k+3))
            colors.extend([ramp((fr["temperature"][i]-750)/1150)]*4)
        ob = mesh_object(f"BF{unit+1} shaft T t={fr['time']:g}s (independent)", vs, fs, fieldmat)
        attr = ob.data.color_attributes.new(name="Temperature", type="FLOAT_COLOR", domain="POINT")
        for i, color in enumerate(colors):
            attr.data[i].color = color
        first = 1+round(fr["time"]*2.4)
        visibility(ob, first, first+11 if index < 24 else 289)
    label("3D REACTIVE POROUS SHAFT", (x, 18.6, 42), .55)
    label("750 K  /  TEMPERATURE SLICE  /  1900 K", (x, 18.6, 40.7), .32)
    label("IRON / SLAG / GAS - 3D VOF", (x, 18.4, 8.8), .42)
    label("20,224 CELLS | CYAN: LIQUID VELOCITY x 10 s", (x, 18.4, 8.1), .25)
    label("INDEPENDENT SHAFT AND HEARTH RUNS", (x, 18.6, 44), .32)

scene.frame_start = 1
scene.frame_end = 289
scene.render.fps = 24
scene.frame_set(289)
print("CFD_GEOMETRY_READY", flush=True)
scene["CFD_source_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
scene["CFD_scope"] = data["scope"]
scene["CFD_times"] = "Hearth 0..12 s; shaft 0..120 s. Independent clocks, not two-way coupled."
encoded = base64.b64encode(zlib.compress(payload.encode(), level=6)).decode()
packed = "\n".join(encoded[i:i+120] for i in range(0, len(encoded), 120))
print("CFD_EMBED_CACHE", len(packed), flush=True)
bpy.data.texts.new("CFD_COMPUTED_FIELDS.json.zlib.base64").write(packed)
print("CFD_CACHE_EMBEDDED", flush=True)
guide = ROOT/"CFD_GUIDE.md"
if guide.exists():
    bpy.data.texts.new("READ_ME_3D_CFD").write(guide.read_text(encoding="utf-8"))
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x = 1400
scene.render.resolution_y = 1000
scene.render.resolution_percentage = 100
camera = scene.camera
# Keep the full steelworks in the viewport; render only the scientific cutaway.
# This bounds render memory on the 8 GB workstation without changing CFD data.
for existing in scene.collection.children:
    existing.hide_render = existing not in (collection, bpy.data.collections.get(
        "13_Physics_section_shells"))
scene["CFD_render_mode"] = "Isolated cutaway render; full environment retained in viewport"
lamp = bpy.data.lights.new("CFD review key", "AREA")
lamp.energy = 5000
lamp.shape = "DISK"
lamp.size = 20
light = bpy.data.objects.new("CFD review key", lamp)
collection.objects.link(light)
light.location = (-52, 35, 35)
light.rotation_euler = (Vector((-62, 18, 12))-light.location).to_track_quat("-Z", "Y").to_euler()


def focus(position, target):
    camera.location = position
    camera.rotation_euler = (Vector(target)-camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 38


focus((-48, 43, 16), (-62, 18, 5.8))
scene.render.threads_mode = "FIXED"
scene.render.threads = 2
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
print("CFD_SAVED_BEFORE_RENDER", flush=True)
scene.render.filepath = str(ROOT/"blender_cfd_hearth.png")
bpy.ops.render.render(write_still=True)
focus((-50, 79, 29), (-62, 18, 23))
camera.data.lens = 32
scene.render.filepath = str(ROOT/"blender_cfd_shaft.png")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
bpy.ops.render.render(write_still=True)
checks = []
for frame in (1, 145, 289):
    scene.frame_set(frame)
    visible = [o for o in collection.objects if not o.hide_render and o.type == "MESH"]
    checks.append({"frame": frame, "visible_meshes": len(visible), "pass": len(visible) == 8})
scene.frame_set(289)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_furnace_cfd.blend"))
report = {"status": "PASS" if all(c["pass"] for c in checks) else "FAIL",
          "checks": checks, "source_sha256": scene["CFD_source_sha256"],
          "objects": len(collection.objects), "scope": data["scope"]}
(ROOT/"blender_cfd_report.json").write_text(json.dumps(report, indent=2))
print("CFD_BLENDER_COMPLETE", json.dumps(report), flush=True)
