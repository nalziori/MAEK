import bpy,json,sys,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from routing_geometry import rounded
bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_connected_steelworks.blend"))
data=json.loads((ROOT/"connected_network.json").read_text(encoding="utf-8"))
errors=[];max_error=0
for l in data["lines"]:
 ob=bpy.data.objects.get(l["id"])
 if not ob or ob.type!="CURVE":errors.append(l["id"]+" missing");continue
 for k in ("from","to","medium","state","source"):
  if ob.get(k)!=l[k]:errors.append(l["id"]+" metadata "+k)
 expected=rounded(l);actual=ob.data.splines[0].points
 if len(expected)!=len(actual):errors.append(l["id"]+" centerline point count");continue
 for a,b in zip(actual,expected):
  gap=math.dist(tuple(ob.matrix_world@__import__("mathutils").Vector(a.co[:3])),b);max_error=max(max_error,gap)
  if gap>1e-4:errors.append(l["id"]+" geometry mismatch");break
 if abs(ob.data.bevel_depth-l["radius_m"])>1e-5:errors.append(l["id"]+" radius mismatch")
archive=bpy.data.collections.get("00_ARCHIVE__unverified_previous_geometry")
assert archive and archive.hide_render and archive.hide_viewport
sc=bpy.context.scene
assert sc.camera.name=="01 Overview to inspection" and sc.frame_start==1 and sc.frame_end==240
for eid in ("BF1.BF","BF2.BF","BF1.TRT","BF2.TRT"):assert bpy.data.objects.get(eid+" concrete foundation")
report={"status":"PASS" if not errors else "FAIL","saved_blend":"maek_connected_steelworks.blend","pipe_objects_checked":len(data["lines"]),"centerlines_checked":"every evaluated POLY control point, endpoints and radius","maximum_position_error_m":max_error,"archived_old_geometry_hidden":True,"active_camera":sc.camera.name,"frames":[sc.frame_start,sc.frame_end],"errors":errors}
(ROOT/"scene_geometry_verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report),flush=True)
assert not errors
