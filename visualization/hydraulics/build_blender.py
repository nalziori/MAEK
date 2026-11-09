"""Bake baseline computed pipe markers and new coupled CFD into the steelworks scene."""
from __future__ import annotations

import base64
import bisect
import hashlib
import json
import zlib
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT/"hydraulic_results.json").read_text(encoding="utf-8"))
catalog = json.loads((ROOT.parent/"pipe_services/pipe_services.json").read_text(encoding="utf-8"))
clip = json.loads((ROOT/"coupled_cfd_baseline.json").read_text(encoding="utf-8"))
assert "unitHearths" in clip
bpy.ops.wm.open_mainfile(filepath=str(ROOT.parent/"pipe_services/maek_pipe_services.blend"))
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 289
scene.render.fps = 24
scene["hydraulic_case"] = "baseline: assumed operating conditions"
scene["flow_marker_speed_scale"] = .1
scene["hydraulic_coupling"] = clip["couplingLabel"]
flow_col = bpy.data.collections.new("17_Calculated_pipe_flow")
cfd_col = bpy.data.collections.new("18_Coupled_CFD_fields")
scene.collection.children.link(flow_col)
scene.collection.children.link(cfd_col)
for prefix in ("14_", "15_"):
    for col in scene.collection.children:
        if col.name.startswith(prefix):
            col.hide_render = col.hide_viewport = True
values = {p["id"]: p for p in data["scenarios"][0]["pipes"]}


def material(name, color):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    shader = m.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Emission Color"].default_value = (*color, 1)
    shader.inputs["Emission Strength"].default_value = .7
    return m


cyan = material("Calculated flow cyan", (.08, 1, .65))
iron = material("Coupled VOF iron", (1, .16, .012))
slag = material("Coupled VOF slag", (.32, .20, .035))
pressure_mat = material("Coupled shaft pressure", (1, 1, 1))
vcol = pressure_mat.node_tree.nodes.new("ShaderNodeVertexColor")
vcol.layer_name = "Pressure"
shader = pressure_mat.node_tree.nodes.get("Principled BSDF")
for socket in ("Base Color", "Emission Color"):
    pressure_mat.node_tree.links.new(vcol.outputs["Color"], shader.inputs[socket])


def mesh_object(name, verts, faces, mat, collection):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    ob = bpy.data.objects.new(name, mesh)
    collection.objects.link(ob)
    return ob


def visibility(ob, first, last):
    action = bpy.data.actions.new(ob.name+" visibility")
    ob.animation_data_create()
    ob.animation_data.action = action
    states = sorted({1: True, first: False, last+1: True}.items())
    for key in ("hide_render", "hide_viewport"):
        curve = action.fcurves.new(data_path=key)
        curve.keyframe_points.add(len(states))
        for point, (frame, hidden) in zip(curve.keyframe_points, states):
            point.co = (frame, float(hidden))
            point.interpolation = "CONSTANT"
    ob.animation_data.action_slot = action.slots[0]


bound = set()
for ob in list(scene.objects):
    line = ob.get("line_id") or ob.name.split(" ")[0]
    if line not in values:
        continue
    p = values[line]
    for key, source in (("pressure_from_pa_abs", "pressureFromPa"),
                        ("pressure_to_pa_abs", "pressureToPa"),
                        ("mass_kg_s", "massKgS"), ("velocity_m_s", "velocityMS"),
                        ("hydraulic_state", "state")):
        ob[key] = p[source]
    bound.add(line)
assert len(bound) == 247

arrow = mesh_object("flow arrow template", [(0, 1, 0), (-.45, -.5, 0), (.45, -.5, 0),
                                             (0, -.5, -.45), (0, -.5, .45)],
                    [(0, 1, 2), (0, 3, 4)], cyan, flow_col)
arrow.hide_render = arrow.hide_viewport = True
arrows = []
for pipe in catalog["pipes"]:
    value = values[pipe["id"]]
    if value["state"] != "flowing":
        continue
    pts = [Vector(p["position"]) for p in pipe["points"]]
    lengths = [0.0]
    for a, b in zip(pts, pts[1:]):
        lengths.append(lengths[-1]+(b-a).length)
    marker = bpy.data.objects.new("FLOW "+pipe["id"], arrow.data)
    flow_col.objects.link(marker)
    marker.scale = (max(.08, min(.8, pipe["radius"]*.8)),)*3
    marker["line_id"] = pipe["id"]
    marker["velocity_m_s"] = value["velocityMS"]
    marker.rotation_mode = "QUATERNION"
    for frame in range(1, 290, 2):
        distance = (.25*lengths[-1]+(frame-1)/24*.1*value["velocityMS"]) % lengths[-1]
        j = min(len(pts)-1, bisect.bisect_right(lengths, distance))
        tangent = (pts[j]-pts[j-1]).normalized()
        point = pts[j-1].lerp(pts[j], (distance-lengths[j-1])/(lengths[j]-lengths[j-1]))
        offset = Vector((0, 0, 1))-tangent*tangent.z
        if offset.length < .1:
            offset = Vector((-1, 0, 0))
        marker.location = point+offset.normalized()*(pipe["radius"]*1.15+.035)
        forward = tangent*(1 if value["velocityMS"] > 0 else -1)
        marker.rotation_quaternion = forward.to_track_quat("Y", "Z")
        marker.keyframe_insert("location", frame=frame)
        marker.keyframe_insert("rotation_quaternion", frame=frame)
    for curve in marker.animation_data.action.fcurves:
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"
    arrows.append(marker)

low = min(min(u["pressure"]) for u in clip["unitShafts"])
high = max(max(u["pressure"]) for u in clip["unitShafts"])
positions = [clip["shaftPositions"][i:i+3] for i in range(0, len(clip["shaftPositions"]), 3)]
for u, x in enumerate((-62, 62)):
    vertices, faces, colors, av, af = [], [], [], [], []
    unit = clip["unitShafts"][u]
    for i, (px, py, pz) in enumerate(positions):
        if abs(py-.5) > .49:
            continue
        start = len(vertices)
        vertices.extend([(x+px+dx, 18.5, 7.2+pz+dz) for dx, dz in
                         [(-.49, -.49), (.49, -.49), (.49, .49), (-.49, .49)]])
        faces.append((start, start+1, start+2, start+3))
        t = (unit["pressure"][i]-low)/(high-low)
        color = (t, .9*(1-abs(2*t-1)), 1-t, 1)
        colors.extend([color]*4)
        velocity = Vector((unit["velocity"][3*i], 0, unit["velocity"][3*i+2]))*.2
        p = Vector((x+px, 18.55, 7.2+pz))
        side = Vector((velocity.z, 0, -velocity.x)).normalized()*.06
        start = len(av)
        av.extend([p+velocity, p+side, p-side])
        af.append((start, start+1, start+2))
    ob = mesh_object("BF"+str(u+1)+" coupled pressure slice", vertices, faces,
                     pressure_mat, cfd_col)
    attribute = ob.data.color_attributes.new(name="Pressure", type="FLOAT_COLOR", domain="POINT")
    for entry, color in zip(attribute.data, colors):
        entry.color = color
    ob["pressure_min_pa_abs"], ob["pressure_max_pa_abs"] = low, high
    mesh_object("BF"+str(u+1)+" solved shaft velocity projection", av, af, cyan, cfd_col)
    for k, state in enumerate(clip["unitHearths"][u]["frames"]):
        for phase, mat in (("iron", iron), ("slag", slag)):
            surf = state[phase]
            verts = [(surf["vertices"][i]+x, surf["vertices"][i+1]+18,
                      surf["vertices"][i+2]+3.2) for i in range(0, len(surf["vertices"]), 3)]
            tris = surf["triangles"]
            ob = mesh_object(f"BF{u+1} coupled {phase} t={state['time']:g}", verts,
                             [tris[i:i+3] for i in range(0, len(tris), 3)], mat, cfd_col)
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            bmesh.ops.bisect_plane(bm, geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                                  plane_co=(0, 18, 0), plane_no=(0, 1, 0),
                                  clear_outer=True, dist=1e-6)
            bm.to_mesh(ob.data)
            bm.free()
            first = 1+round(state["time"]*24)
            visibility(ob, first, min(289, first+23))
            ob["computed_hearth_surface"] = True

cfd_col.hide_render = cfd_col.hide_viewport = True
camera_data = bpy.data.cameras.new("HYDRAULIC CFD camera")
camera = bpy.data.objects.new("HYDRAULIC CFD camera", camera_data)
scene.collection.objects.link(camera)
camera.location = (-62, 68, 28)
camera.rotation_euler = (Vector((-62, 18, 22))-camera.location).to_track_quat("-Z", "Y").to_euler()
camera.data.lens = 45
for filename in ("HYDRAULIC_CFD_GUIDE.md", "hydraulic_results.json"):
    bpy.data.texts.new(filename).write((ROOT/filename).read_text(encoding="utf-8"))
for case in data["scenarios"]:
    raw = (ROOT/case["clipName"]).read_bytes()
    encoded = base64.b64encode(zlib.compress(raw)).decode()
    bpy.data.texts.new(case["clipName"]+".zlib.base64").write(
        "\n".join(encoded[i:i+100] for i in range(0, len(encoded), 100)))
scene.frame_set(1)
target = ROOT/"maek_hydraulic_cfd.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(target))
bpy.ops.wm.open_mainfile(filepath=str(target))
for frame in (1, 145, 289):
    bpy.context.scene.frame_set(frame)
    visible = [o for o in bpy.data.collections["18_Coupled_CFD_fields"].objects
               if o.get("computed_hearth_surface") and not o.hide_render]
    assert len(visible) == 4, (frame, len(visible))
for line, value in values.items():
    assert abs(bpy.data.objects[line]["mass_kg_s"]-value["massKgS"]) < 1e-8
report = dict(status="PASS", pipes=len(bound), animated_flow_markers=len(arrows),
              saved_file_reopened=True, verified_hearth_frames=[1, 145, 289],
              baseline_only_animation=True, coupled_cases_embedded=3)
(ROOT/"blender_hydraulic_report.json").write_text(json.dumps(report, indent=2))
print("HYDRAULIC_BLEND_VERIFIED", json.dumps(report), flush=True)
