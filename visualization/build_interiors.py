import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_collision_ready.blend"))
sc=bpy.context.scene
data=json.loads((ROOT/"collision_network.json").read_text())
data["sources"].append({"id":"DEMO","detail":"Fictional indoor inspection training closed loop; not a steelworks engineering drawing"})
coll=bpy.data.collections.new("09_Walkable_interiors");sc.collection.children.link(coll)
steel=bpy.data.materials["CONNECTED structural blue grey"];floor=bpy.data.materials["CONNECTED concrete"];silver=bpy.data.materials["CONNECTED galvanized cladding"];yellow=bpy.data.materials["CONNECTED safety yellow"];orange=bpy.data.materials["CONNECTED MAEK inspection orange"];dark=bpy.data.materials["CONNECTED dark painted steel"]
cache={};asset=""
def box(name,p,d,m=steel):
 key=m.name
 if key not in cache:
  me=bpy.data.meshes.new("Interior box "+key)
  vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]
  fs=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
  me.from_pydata(vs,[],[tuple(reversed(f)) for f in fs]);me.materials.append(m);cache[key]=me
 ob=bpy.data.objects.new(name,cache[key]);coll.objects.link(ob);ob.location=p;ob.scale=d;ob["interior_asset_id"]=asset;return ob
def text(name,p):
 cu=bpy.data.curves.new(name,"FONT");cu.body=name;cu.size=.38;cu.align_x="CENTER";cu.materials.append(yellow)
 ob=bpy.data.objects.new("Label "+name,cu);coll.objects.link(ob);ob.location=p;ob.rotation_euler=(math.pi/2,0,0)
def pipe(l):
 from routing_geometry import rounded
 ps=rounded(l);cu=bpy.data.curves.new(l["id"],"CURVE");cu.dimensions="3D";cu.bevel_depth=l["radius_m"];cu.bevel_resolution=3
 sp=cu.splines.new("POLY");sp.points.add(len(ps)-1)
 for p,v in zip(sp.points,ps):p.co=(*v,1)
 cu.materials.append(silver);o=bpy.data.objects.new(l["id"],cu);coll.objects.link(o)
 for k in ("id","from","to","medium","source","state"):o[k]=l[k]
 return o
rooms=[]
for o in list(sc.objects):
 if o.hide_render or any(c.hide_render for c in o.users_collection):continue
 n=o.name
 if n=="cast house" or n.startswith("cast house.") or n=="stockhouse" or n.startswith("stockhouse.") or n.startswith("Background Rolling and service hall"):
  x,y,z=o.location;w,dep,h=o.dimensions
  kind="CASTHOUSE" if n.startswith("cast house") else "STOCKHOUSE" if n.startswith("stockhouse") else "SERVICE_HALL"
  rid=("BF1" if x<0 else "BF2")+"."+kind if kind!="SERVICE_HALL" else "SERVICE."+str(round(x))
  rooms.append({"id":rid,"x":x,"y":y,"width":w,"depth":dep,"height":h,"kind":kind})
  o.hide_render=True;o.hide_set(True)
 if n.startswith("cast house corrugation"):o.hide_render=True;o.hide_set(True)
for room in rooms:
 x,y,w,dep,h=(room[k] for k in ("x","y","width","depth","height"));rid=room["id"];asset=rid if room["kind"]!="SERVICE_HALL" else "BUILDING."+str(round(x))
 box(rid+" floor",(x,y,.05),(w,dep,.20),floor)
 if room["kind"]=="STOCKHOUSE":box(rid+" roof",(x,y,h+.15),(w,dep,.30),silver)
 for s in (-1,1):
  box(rid+" side wall",(x+s*(w/2-.15),y,h/2),(.30,dep,h),silver)
  yy=y+s*(dep/2-.15)
  for side in (-1,1):
   width=(w-6)/2
   box(rid+" door side",(x+side*(3+width/2),yy,h/2),(width,.30,h),silver)
  box(rid+" door lintel",(x,yy,(h+5.5)/2),(6,.30,h-5.5),silver)
 for yy in (y-dep/2+2,y,y+dep/2-2):
  for side in (-1,1):box(rid+" column",(x+side*(w/2-.8),yy,h/2),(.35,.35,h),steel)
 for yy in (y-dep*.3,y,y+dep*.3):
  box(rid+" roof beam",(x,yy,h-.5),(w-.6,.26,.35),steel)
  box(rid+" luminaire",(x,yy,h-.95),(2.4,.5,.15),silver)
  ld=bpy.data.lights.new(rid+" interior lamp","AREA");ld.energy=1800 if w<30 else 5000;ld.shape="DISK";ld.size=5
  lo=bpy.data.objects.new(rid+" interior lamp",ld);coll.objects.link(lo);lo.location=(x,yy,h-1.1)
 # Marked central walkway, kept free of machinery.
 for side in (-1,1):
  mark=box("road center interior walkway",(x+side*2.0,y,.156),(.09,dep-.7,.012),yellow)
 text(rid+"  |  WALKWAY",(x,y-dep/2-.18,4.5))
 if room["kind"]=="CASTHOUSE":
  asset=rid+".CRANE"
  for side in (-1,1):box(rid+" crane runway",(x+side*9,y,8.4),(.25,dep-2,.35),steel)
  box(rid+" bridge crane",(x,y+1.5,8.8),(18.5,.9,.45),yellow)
  box(rid+" crane trolley",(x+5,y+1.5,8.25),(1.8,1.2,.65),dark)
  asset=rid+".TROUGH"
  box(rid+" demonstration trough bed",(x+6,y,.5),(2.4,16,.7),dark)
  for s in (-1,1):box(rid+" trough side",(x+6+s*1.15,y,1),(.15,16,.4),steel)
  # A connected, cold inspection training loop: no simulated molten metal.
  prefix=rid+".TRAIN"
  for tag,yy in (("PUMP",48),("COOLER",58)):
   eid=prefix+"."+tag;asset=eid
   box(eid,(x-7,yy,.9),(1.6,1.8,1.5),steel)
   data["devices"][eid]={"kind":"inspection_training_skid","center":[x-7,yy,.9],"dimensions":[1.6,1.8,1.5],"source":"DEMO","geometry_basis":"fictional training equipment"}
  specs=[("P.OUT",(x-7,48.9,1.2),"PUMP"),("P.IN",(x-6.2,48,1),"PUMP"),("C.IN",(x-7,57.1,1.2),"COOLER"),("C.OUT",(x-6.2,58,1),"COOLER")]
  for name,pos,eq in specs:data["nodes"][prefix+"."+name]={"position":list(pos),"medium":"CW","device":prefix+"."+eq,"kind":"port"}
  for tag,start,end,via in [("SUP","P.OUT","C.IN",[(x-7,50,1.2),(x-7,50,2.4),(x-7,55,2.4),(x-7,55,1.2)]),("RET","C.OUT","P.IN",[(x-4.8,58,1),(x-4.8,48,1)])]:
   a,b=prefix+"."+start,prefix+"."+end
   l={"id":prefix+"-"+tag,"from":a,"to":b,"medium":"CW","radius_m":.12,"state":"open","source":"DEMO","points":[data["nodes"][a]["position"]]+list(map(list,via))+[data["nodes"][b]["position"]],"exact_polyline":False}
   data["lines"].append(l);pipe(l)
  for a,b in (("P.IN","P.OUT"),("C.IN","C.OUT")):data["internal_connections"].append({"from":prefix+"."+a,"to":prefix+"."+b,"active":True,"kind":"training equipment"})
  data["required_routes"].append({"from":prefix+".P.OUT","to":prefix+".P.IN","caption":rid+" inspection water loop"})
  asset=rid+".BENCH"
  box(rid+" inspection bench",(x-8,y+1,1.1),(2,1,.15),steel)
  for dx in (-.8,.8):
   for dy in (-.35,.35):box(rid+" bench leg",(x-8+dx,y+1+dy,.625),(.08,.08,.95),steel)
  box(rid+" UT case",(x-8,y+1,1.35),(.55,.35,.3),orange)
  text("COLD INSPECTION TRAINING LOOP",(x-7,46.8,2.8))
 else:
  for side in (-1,1):
   asset=rid+".WORKCELL."+str(side)
   box(rid+" workbench",(x+side*(w/2-3.3),y,1.05),(2,4,1.8),steel)
   box(rid+" tool storage",(x+side*(w/2-3.3),y+4,1.45),(2,1.2,2.6),dark)
sc["network_file"]="interior_network.json"
(ROOT/"interior_network.json").write_text(json.dumps(data,indent=2),encoding="utf-8")
from validate_connected_network import validate
result=validate(data,write_report=False)
(ROOT/"interior_connectivity_report.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
assert result["status"]=="PASS"
from audit_asset_overlap import audit
result=audit("interior_overlap_report.json")
assert result["unreviewed_overlap_pairs"]==0,"Review interior_overlap_report.json"
from export_unity_geometry import export_scene,OUT
export_scene(data);(OUT/"interior_rooms.json").write_text(json.dumps({"rooms":rooms}),encoding="utf-8")
(ROOT/"interior_rooms.json").write_text(json.dumps({"rooms":rooms},indent=2),encoding="utf-8")
ca=bpy.data.cameras.new("Interior walkthrough");cam=bpy.data.objects.new("Interior walkthrough",ca);coll.objects.link(cam);ca.lens=23
for f,pos,target in [(1,(-62,32,2.0),(-62,53,2.2)),(100,(-62,44,2.0),(-64,55,2.4)),(180,(-61,51,2.0),(-68,54,1.7))]:
 cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat("-Z","Y").to_euler();cam.keyframe_insert(data_path="location",frame=f);cam.keyframe_insert(data_path="rotation_euler",frame=f)
sc.camera=cam;sc.frame_set(100)
sc["verified_pipe_lines"]=len(data["lines"]);sc["connectivity_report"]="interior_connectivity_report.json";sc["asset_overlap_report"]="interior_overlap_report.json"
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_interior_ready.blend"))
sc.cycles.samples=16;sc.render.filepath=str(ROOT/"interior_cast_house.png");bpy.ops.render.render(write_still=True)
sc.frame_set(180);sc.render.filepath=str(ROOT/"interior_inspection.png");bpy.ops.render.render(write_still=True)
print("INTERIOR_COMPLETE",len(rooms),len(data["lines"]),flush=True)

