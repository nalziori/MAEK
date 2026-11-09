import bpy,sys,json,re,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_ray_tri
from collections import Counter
ROOT=Path(__file__).resolve().parent
network=json.loads((ROOT/"connected_network.json").read_text(encoding="utf-8"))
line_map={l["id"]:l for l in network["lines"]};devs=network["devices"];nodes=network["nodes"]
def group(ob):
 n=ob.name
 if ob.get("interior_asset_id") and not n.startswith("road center"):return ob["interior_asset_id"]
 if n.startswith(("Label ","FLOW ","road center","UT electrical","UT display")) or ob.type=="FONT":return None
 for eid in sorted(devs,key=len,reverse=True):
  if n==eid or n.startswith(eid+" "):
   if ".STAVE" in eid:return eid.split(".")[0]+".BF"
   return eid
 for lid in line_map:
  if n==lid or n.startswith(lid+" "):return lid
 if ob.get("line_id") in line_map:return ob["line_id"]
 x=ob.location.x
 # Curves constructed in world space have identity object transforms.
 if ob.type=="CURVE" and len(ob.data.splines) and ob.data.splines[0].type=="POLY":x=sum(p.co.x for p in ob.data.splines[0].points)/len(ob.data.splines[0].points)
 unit="BF1" if x<0 else "BF2"
 if n.startswith("Background "):return "BUILDING."+str(round(ob.location.x))
 if n.startswith(("cast house",)):return unit+".CASTHOUSE"
 if n.startswith("stockhouse"):return unit+".STOCKHOUSE"
 if n.startswith(("conveyor","inclined conveyor")):return unit+".CONVEYOR"
 if n.startswith(("furnace ","open-center","guardrail","diagonal bracing","ladder ")):return unit+".TOWER"
 if n.startswith("gas main "):return unit+".RACK."+str(round(ob.location.x))
 if n.startswith(("Inspection ","UT cart")):return "INSPECTION_PLATFORM"
 if n.startswith(("UT meter","UT contact probe")):return "INSPECTION_TOOL"
 if n in ("Process yard","Distant ground","Site road"):return n
 return n
def visible(ob):
 return ob.type in ("MESH","CURVE") and not ob.hide_render and any(not c.hide_render and not c.name.startswith("00_ARCHIVE") for c in ob.users_collection)
def inside(tree,point):
 nearest=tree.find_nearest(point)
 if nearest[0] is None or nearest[3]<.002:return False
 direction=Vector((.43171,.71513,.85329)).normalized();origin=Vector(point);count=0
 for _ in range(128):
  hit=tree.ray_cast(origin,direction)
  if hit[0] is None:return count%2==1
  count+=1;origin=hit[0]+direction*.0002
 raise RuntimeError("Containment ray did not terminate")
def contact_in_zones(overlaps,av,ats,bv,bts,zones):
 # Verify finite triangle intersections lie near a declared nozzle/tee, not elsewhere.
 for ia,ib in overlaps:
  va=[av[k] for k in ats[ia]];vb=[bv[k] for k in bts[ib]]
  for edges,tri in ((va,vb),(vb,va)):
   for k in range(3):
    start,end=edges[k],edges[(k+1)%3];direction=end-start
    if direction.length<1e-8:continue
    hit=intersect_ray_tri(*tri,direction,start,True)
    if hit is None:continue
    t=(hit-start).dot(direction)/direction.length_squared
    if t<-.00001 or t>1.00001:continue
    if not any((hit-Vector(p)).length<=r for p,r in zones):return False
 return True
def audit(outname):
 global network,line_map,devs,nodes
 network=json.loads((ROOT/bpy.context.scene.get("network_file","connected_network.json")).read_text(encoding="utf-8"))
 line_map={l["id"]:l for l in network["lines"]};devs=network["devices"];nodes=network["nodes"]
 dg=bpy.context.evaluated_depsgraph_get();entries=[];solid={}
 for ob in bpy.context.scene.objects:
  if not visible(ob):continue
  aid=group(ob)
  if not aid:continue
  ev=ob.evaluated_get(dg);me=ev.to_mesh()
  if not me or not len(me.vertices):continue
  me.calc_loop_triangles();vs=[ev.matrix_world@v.co for v in me.vertices];ts=[tuple(t.vertices) for t in me.loop_triangles]
  lo=Vector(tuple(min(v[k] for v in vs) for k in range(3)));hi=Vector(tuple(max(v[k] for v in vs) for k in range(3)))
  edges=Counter(tuple(sorted((t[k],t[(k+1)%3]))) for t in ts for k in range(3))
  solid[ob.name]=all(n==2 for n in edges.values())
  tree=BVHTree.FromPolygons(vs,ts,all_triangles=True,epsilon=0)
  entries.append((lo.x,ob.name,aid,lo,hi,tree,vs,ts));ev.to_mesh_clear()
 entries.sort(key=lambda e:e[0]);unexpected=[];expected=[];tested=0
 for i,a in enumerate(entries):
  _,an,aid,al,ah,at,av,ats=a
  for b in entries[i+1:]:
   if b[0]>=ah.x-.002:break
   _,bn,bid,bl,bh,bt,bv,bts=b
   if aid==bid:continue
   if not all(min(ah[k],bh[k])-max(al[k],bl[k])>.002 for k in range(3)):continue
   overlaps=at.overlap(bt);tested+=1
   contained=False
   if not overlaps:
    if solid[an] and all(al[k]<bl[k] and ah[k]>bh[k] for k in range(3)):contained=inside(at,bv[0])
    if not contained and solid[bn] and all(bl[k]<al[k] and bh[k]>ah[k] for k in range(3)):contained=inside(bt,av[0])
    if not contained:continue
   row={"a":an,"b":bn,"asset_a":aid,"asset_b":bid,"surface_triangle_pairs":len(overlaps),"overlap_box":[list(Vector(tuple(max(al[k],bl[k]) for k in range(3)))),list(Vector(tuple(min(ah[k],bh[k]) for k in range(3))))]}
   reason=None;zones=[]
   if aid in line_map and bid in line_map:
    la,lb=line_map[aid],line_map[bid];shared=set((la["from"],la["to"]))&set((lb["from"],lb["to"]))
    if shared:
     reason="declared pipe joint";zones=[(nodes[k]["position"],(la["radius_m"]+lb["radius_m"])*2.2+.15) for k in shared]
   for lid,did in ((aid,bid),(bid,aid)):
    if lid not in line_map or did not in devs:continue
    l=line_map[lid]
    matches=[nodes[n]["position"] for n in (l["from"],l["to"]) if nodes[n]["device"]==did]
    if ".BF" in did:
     matches += [nodes[n]["position"] for n in (l["from"],l["to"]) if nodes[n]["device"] and nodes[n]["device"].startswith(did.split(".")[0]+".STAVE")]
    if matches:
     reason="declared equipment nozzle";zones=[(p,max(.5,l["radius_m"]*3.2)) for p in matches]
   if {aid,bid}=={"INSPECTION_TOOL","BF1-W002"}:reason="contact probe";zones=[((-72,-12,6.5),.5)]
   if reason and not contact_in_zones(overlaps,av,ats,bv,bts,zones):reason=None
   if contained:row["containment"]=True
   if reason:row["reason"]=reason;expected.append(row)
   else:unexpected.append(row)
 summary={"objects":len(entries),"broadphase_pairs":tested,"declared_contact_pairs":len(expected),"unreviewed_overlap_pairs":len(unexpected),"overlaps":unexpected,"declared_contacts":expected}
 (ROOT/outname).write_text(json.dumps(summary,indent=2),encoding="utf-8")
 print(json.dumps({"objects":len(entries),"candidates":len(unexpected),"pairs":unexpected[:35]}),flush=True)
 return summary
if __name__=="__main__":
 target=ROOT/(sys.argv[sys.argv.index("--")+1] if "--" in sys.argv else "maek_connected_steelworks.blend")
 bpy.ops.wm.open_mainfile(filepath=str(target));audit("asset_overlap_before.json")
