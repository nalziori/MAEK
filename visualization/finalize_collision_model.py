import bpy,sys,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from audit_asset_overlap import audit,inside,contact_in_zones
vs=[Vector((x,y,z)) for x,y,z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
tree=BVHTree.FromPolygons(vs,faces,all_triangles=True)
assert inside(tree,Vector((0,0,0))) and not inside(tree,Vector((2,0,0)))
va=[Vector(p) for p in [(-1,0,-1),(1,0,-1),(0,0,1)]]
vb=[Vector(p) for p in [(0,-1,-.5),(0,1,-.5),(0,0,.5)]]
assert not contact_in_zones([(0,0)],va,[(0,1,2)],vb,[(0,1,2)],[((10,10,10),.1)])
assert contact_in_zones([(0,0)],va,[(0,1,2)],vb,[(0,1,2)],[((0,0,0),3)])
print("COLLISION_CHECKER_NEGATIVE_CASES_PASS",flush=True)
bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_collision_ready.blend"))
result=audit("asset_overlap_final.json")
if result["unreviewed_overlap_pairs"]:raise RuntimeError("Remaining intersections or containment; inspect asset_overlap_final.json")
sc=bpy.context.scene;sc["asset_overlap_report"]="asset_overlap_final.json"
sc["collision_audit_scope"]="Visible distinct assemblies; triangle intersections and closed-shell containment; declared contacts restricted to local port zones; 2mm broadphase tolerance"
current=bpy.data.collections["08_Cameras"]
ca=bpy.data.cameras.new("05 Stair access");cam=bpy.data.objects.new("05 Stair access",ca);current.objects.link(cam)
cam.location=(-96,-47,23);cam.rotation_euler=(Vector((-73,-18,7))-cam.location).to_track_quat("-Z","Y").to_euler();ca.lens=48
hero=bpy.data.objects["01 Overview to inspection"];sc.camera=hero;sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_collision_ready.blend"))
for camera,name in [(bpy.data.objects["02 Connected BF1"],"collision_furnace.png"),(cam,"collision_stair_access.png"),(hero,"collision_overview.png")]:
 sc.camera=camera;sc.render.filepath=str(ROOT/name);bpy.ops.render.render(write_still=True)
print("COLLISION_MODEL_VERIFIED_AND_RENDERED",flush=True)
