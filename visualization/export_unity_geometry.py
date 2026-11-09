"""Bake visible assets to an engine-neutral binary; explicit Blender Z-up -> Unity Y-up.
Collider grouping follows the audited assembly IDs, never a convex hull around pipe racks.
"""
import bpy,bmesh,json,struct,math
from pathlib import Path
from collections import defaultdict
from mathutils import Vector
from audit_asset_overlap import group,visible
ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/"unity"/"MAEKInspection"/"Assets"/"MAEK"/"Source"
def export_scene(network):
 OUT.mkdir(parents=True,exist_ok=True)
 groups=defaultdict(list)
 for ob in bpy.context.scene.objects:
  if not visible(ob) and not (ob.type=="FONT" and not ob.hide_render and any(not c.hide_render for c in ob.users_collection)):continue
  aid=group(ob)
  groups[aid if aid else "DECOR."+ob.name].append(ob)
 mats=[];matmap={}
 def material_index(m):
  key=m.name if m else "default"
  if key not in matmap:
   color=list(m.diffuse_color) if m else [.5,.5,.5,1]
   p=m.node_tree.nodes.get("Principled BSDF") if m and m.use_nodes else None
   if p:color=list(p.inputs["Base Color"].default_value)
   matmap[key]=len(mats)
   mats.append({"name":key,"color":color,"metallic":float(p.inputs["Metallic"].default_value) if p else 0,"smoothness":1-float(p.inputs["Roughness"].default_value) if p else .3})
  return matmap[key]
 dg=bpy.context.evaluated_depsgraph_get();assets=[];total=0
 with (OUT/"maek_geometry.bytes").open("wb") as f:
  f.write(b"MAEKCOL1");f.write(struct.pack("<i",len(groups)))
  for aid,objects in sorted(groups.items()):
   vertices=[];normals=[];sub=defaultdict(list)
   for ob in objects:
    ev=ob.evaluated_get(dg);me=ev.to_mesh()
    if not me:continue
    # Fix inward primitive faces inherited from the earlier visual-only generator.
    bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free()
    me.calc_loop_triangles()
    matrix=ev.matrix_world;normal_matrix=matrix.to_3x3().inverted().transposed()
    corner=me.corner_normals
    for tri in me.loop_triangles:
     mi=material_index(me.materials[tri.material_index] if len(me.materials)>tri.material_index else None)
     ids=[]
     # Swapping Y/Z changes handedness; reverse winding to retain outward surfaces.
     for li in reversed(tri.loops):
      vi=me.loops[li].vertex_index;p=matrix@me.vertices[vi].co;n=(normal_matrix@corner[li].vector).normalized()
      ids.append(len(vertices));vertices.append((p.x,p.z,p.y));normals.append((n.x,n.z,n.y))
     sub[mi].extend(ids)
    ev.to_mesh_clear()
   if not vertices:raise RuntimeError("Empty export asset "+aid)
   lo=[min(p[k] for p in vertices) for k in range(3)];hi=[max(p[k] for p in vertices) for k in range(3)]
   center=[(a+b)/2 for a,b in zip(lo,hi)];size=[b-a for a,b in zip(lo,hi)]
   collider="none" if aid.startswith("DECOR.") else "box" if aid in ("Process yard","Distant ground","Site road") else "mesh"
   raw=aid.encode("utf-8");f.write(struct.pack("<i",len(raw)));f.write(raw)
   f.write(struct.pack("<ii",len(vertices),len(sub)))
   for p,n in zip(vertices,normals):f.write(struct.pack("<6f",*(p[k]-center[k] for k in range(3)),*n))
   for mi,indices in sorted(sub.items()):
    f.write(struct.pack("<ii",mi,len(indices)));f.write(struct.pack("<%di"%len(indices),*indices))
   assets.append({"id":aid,"position":center,"size":size,"collider":collider,"vertices":len(vertices),"triangles":sum(map(len,sub.values()))//3,"objects":[o.name for o in objects]})
   total+=len(vertices)
   for o in objects:o["maek_asset_id"]=aid;o["unity_collider"]=collider;o["unity_static"]=collider!="none"
 manifest={"format":"MAEKCOL1","units":"metres","coordinate_map":"Unity(x,y,z) = Blender(x,z,y); winding reversed","basis":"public PFD fictional spatial layout","materials":mats,"assets":assets,"pipe_count":len(network["lines"])}
 (OUT/"maek_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
 (OUT/"collision_network.json").write_text(json.dumps(network,indent=2),encoding="utf-8")
 (ROOT/"unity_export_report.json").write_text(json.dumps({"assets":len(assets),"collider_assets":sum(a["collider"]!="none" for a in assets),"vertices":total,"bytes":(OUT/"maek_geometry.bytes").stat().st_size},indent=2),encoding="utf-8")
 print("UNITY_GEOMETRY_EXPORTED",len(assets),total,flush=True)
if __name__=="__main__":
 bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_collision_ready.blend"))
 export_scene(json.loads((ROOT/"collision_network.json").read_text()))
 bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_collision_ready.blend"))

