import bpy, math, json, sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from connected_network import export
from routing_geometry import rounded
from validate_connected_network import validate
data=export(); report=validate(data)
if report["status"]!="PASS":raise RuntimeError("Connectivity validation failed; inspect connectivity_report.json")
bpy.ops.wm.open_mainfile(filepath=str(ROOT/"maek_steelworks_detailed.blend"))
sc=bpy.context.scene
# Archive the old unverified geometry inside the new file; original .blend is untouched.
old=list(bpy.data.objects)
archive=bpy.data.collections.new("00_ARCHIVE__unverified_previous_geometry");sc.collection.children.link(archive)
back=bpy.data.collections.new("01_Background_buildings");sc.collection.children.link(back)
for ob in old:
 if ob.type=="MESH" and ob.location.y>76 and ob.name.startswith(("Rolling and service hall","Hall roof","Hall facade rib")):
  clone=ob.copy();clone.data=ob.data;back.objects.link(clone);clone.name="Background "+ob.name;clone.location.y+=25
 for c in list(ob.users_collection):c.objects.unlink(ob)
 archive.objects.link(ob)
archive.hide_render=True;archive.hide_viewport=True
cols={}
for name in ("02_Process_equipment","03_Connected_pipes","04_Structures","05_Inspection","06_Flow_arrows","07_Labels","08_Cameras"):
 c=bpy.data.collections.new(name);sc.collection.children.link(c);cols[name]=c
current=cols["02_Process_equipment"]
def link(o):current.objects.link(o);return o
def material(name,color,metal=.35,rough=.6,weather=False):
 m=bpy.data.materials.new("CONNECTED "+name);m.diffuse_color=(*color,1);m.use_nodes=True
 nt=m.node_tree;p=nt.nodes.get("Principled BSDF");p.inputs["Base Color"].default_value=(*color,1);p.inputs["Metallic"].default_value=metal;p.inputs["Roughness"].default_value=rough
 if weather:
  noise=nt.nodes.new("ShaderNodeTexNoise");noise.inputs["Scale"].default_value=5;noise.inputs["Detail"].default_value=3
  ramp=nt.nodes.new("ShaderNodeValToRGB")
  ramp.color_ramp.elements[0].color=(*(x*.55 for x in color),1);ramp.color_ramp.elements[1].color=(*(min(x*1.35,1) for x in color),1)
  nt.links.new(noise.outputs["Fac"],ramp.inputs[0]);nt.links.new(ramp.outputs["Color"],p.inputs["Base Color"])
  bump=nt.nodes.new("ShaderNodeBump");bump.inputs["Strength"].default_value=.14;bump.inputs["Distance"].default_value=.02;nt.links.new(noise.outputs["Fac"],bump.inputs["Height"]);nt.links.new(bump.outputs[0],p.inputs["Normal"])
 return m
steel=material("structural blue grey",(.15,.23,.25),.6,.7,True)
dark=material("dark painted steel",(.07,.10,.11),.65)
shell=material("aged furnace casing",(.29,.19,.13),.6,.76,True)
silver=material("galvanized cladding",(.49,.54,.53),.75,.42,True)
gasmat=material("BFG weathered warm grey",(.35,.31,.23),.55,.8,True)
watermat=material("cooling water muted blue",(.12,.29,.33),.55,.6,True)
yellow=material("safety yellow",(.78,.48,.07),.15)
red=material("oxide red roofing",(.40,.14,.07),.45,.7,True)
concrete=material("concrete",(.30,.32,.31),0,.9,True)
asphalt=material("road",(.085,.10,.11),0,.95)
light=material("white lettering",(.85,.88,.86),0,.6)
orange=material("MAEK inspection orange",(.95,.32,.035),.2)
black=material("rubber",(.02,.027,.03),0)
screen=material("instrument display",(.02,.28,.32),.3,.25)
rust=material("inspection surface corrosion",(.35,.095,.024),.35,.92,True)
colors={"BFG":gasmat,"AIR":silver,"CW":watermat,"COMB_AIR":steel,"FLUE":dark,"WASH":watermat,"SLURRY":shell}
cache={}
def mesh(kind,mat):
 key=(kind,mat.name)
 if key in cache:return cache[key]
 me=bpy.data.meshes.new(kind+" "+mat.name)
 if kind=="box":
  vs=[(x/2,y/2,z/2) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]
  fs=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
 else:
  N=32;vs=[(math.cos(i*math.tau/N),math.sin(i*math.tau/N),z) for z in (-.5,.5) for i in range(N)]
  fs=[tuple(reversed(range(N))),tuple(range(N,2*N))]+[(i,(i+1)%N,(i+1)%N+N,i+N) for i in range(N)]
 me.from_pydata(vs,[],fs);me.materials.append(mat)
 if kind!="box":
  for p in me.polygons:
   if len(p.vertices)==4:p.use_smooth=True
 cache[key]=me;return me
def box(n,p,d,m=steel):
 o=link(bpy.data.objects.new(n,mesh("box",m)));o.location=p;o.scale=d;return o
def rod(n,a,b,r,m=steel):
 a,b=Vector(a),Vector(b);v=b-a;o=link(bpy.data.objects.new(n,mesh("cyl",m)));o.location=(a+b)/2;o.rotation_euler=v.to_track_quat("Z","Y").to_euler();o.scale=(r,r,v.length);return o
def beam(n,a,b,w=.15,m=steel):
 a,b=Vector(a),Vector(b);v=b-a;o=box(n,(a+b)/2,(w,w,v.length),m);o.rotation_euler=v.to_track_quat("Z","Y").to_euler();return o
def tube(n,ps,r,m):
 cu=bpy.data.curves.new(n,"CURVE");cu.dimensions="3D";cu.resolution_u=1;cu.bevel_depth=r;cu.bevel_resolution=3;cu.use_fill_caps=False
 sp=cu.splines.new("POLY");sp.points.add(len(ps)-1)
 for p,v in zip(sp.points,ps):p.co=(*v,1)
 cu.materials.append(m);return link(bpy.data.objects.new(n,cu))
def ring(n,center,radius,tube_radius,m=steel,axis="Z"):
 ps=[]
 for j in range(49):
  t=j*math.tau/48;c,s=radius*math.cos(t),radius*math.sin(t)
  local={"Z":(c,s,0),"X":(0,c,s),"Y":(c,0,s)}[axis];ps.append(tuple(center[i]+local[i] for i in range(3)))
 return tube(n,ps,tube_radius,m)
def lathe(n,x,y,profile,m):
 N=48;vs=[(x+r*math.cos(i*math.tau/N),y+r*math.sin(i*math.tau/N),z) for z,r in profile for i in range(N)]
 fs=[]
 for k in range(len(profile)-1):
  for i in range(N):j=(i+1)%N;fs.append((k*N+i,k*N+j,(k+1)*N+j,(k+1)*N+i))
 fs.append(tuple(reversed(range(N))));fs.append(tuple((len(profile)-1)*N+i for i in range(N)))
 me=bpy.data.meshes.new(n);me.from_pydata(vs,[],fs);me.materials.append(m)
 for p in me.polygons:p.use_smooth=len(p.vertices)==4
 return link(bpy.data.objects.new(n,me))
def label(text,pos,size=.65,mat=light):
 cu=bpy.data.curves.new("label "+text,"FONT");cu.body=text;cu.align_x="CENTER";cu.size=size;cu.extrude=.003;cu.materials.append(mat)
 o=link(bpy.data.objects.new("Label "+text,cu));o.location=pos;o.rotation_euler=(math.pi/2,0,0);return o
def platform(x,y,z,w=18,hole=12):
 thick=(w-hole)/2
 for s in (-1,1):
  box("open-center platform",(x+s*(w+hole)/4,y,z),(thick,w,.18),steel)
  box("open-center platform",(x,y+s*(w+hole)/4,z),(hole,thick,.18),steel)
  for rr in (w/2-.15,hole/2+.1):
   rod("guardrail",(x-w/2,y+s*rr,z+1.1),(x+w/2,y+s*rr,z+1.1),.035,yellow)
  for xx in range(-8,9,2):rod("guardrail stanchion",(x+xx,y+s*(w/2-.15),z),(x+xx,y+s*(w/2-.15),z+1.1),.025,yellow)
# Site background kept subordinate to explicitly connected process trains.
current=cols["04_Structures"]
box("Process yard",(0,26,-.4),(330,230,.7),concrete)
box("Distant ground",(0,0,-.85),(2500,2500,.2),concrete)
box("Site road",(0,-43,.01),(310,12,.06),asphalt)
for x in range(-144,145,12):box("road center dash",(x,-43,.055),(5,.12,.02),light)
# Equipment shells are deliberate black boxes; ports do not implicitly mix their services.
current=cols["02_Process_equipment"]
for eid,d in data["devices"].items():
 x,y,z=d["center"];w,dep,h=d["dimensions"];kind=d["kind"]
 if kind=="furnace":
  o=lathe(eid,x,y,[(3,5.7),(17.5,5.7),(23,4.2),(37,3.6),(42,2.4),(46,2.4)],shell)
  rod(eid+" charging vessel",(x,y,46),(x,y,51),1.8,steel)
 elif kind=="dust_catcher":
  o=lathe(eid,x,y,[(3,.7),(7,3.2),(21,3.2),(24,1.35)],gasmat)
  for zz in (8,14,20):ring(eid+" shell seam",(x,y,zz),3.23,.04,dark)
  box(eid+" sealed dust bin",(x,y,1.5),(4,4,3),dark)
 elif kind=="scrubber":
  o=lathe(eid,x,y,[(.5,1.2),(3,2.5),(17,2.5),(20,1.8),(21,.9)],silver)
  for zz in (4,9,14,18):ring(eid+" cladding seam",(x,y,zz),2.52,.035,dark)
 elif kind=="stove":
  o=lathe(eid,x,y,[(0,3),(26,3),(28,2.8),(29.5,1.8),(30,.2)],shell)
  for zz in range(2,27,3):ring(eid+" shell band",(x,y,zz),3.02,.035,dark)
  for xx in (x-.35,x+.35):rod(eid+" ladder",(xx,y-3.08,1),(xx,y-3.08,27),.035,steel)
  for zz in range(1,28):rod(eid+" ladder rung",(x-.35,y-3.08,zz),(x+.35,y-3.08,zz),.025,steel)
  label(eid+" "+d["mode"],(x,y-3.13,20),.48)
 elif kind=="stack":
  o=lathe(eid,x,y,[(0,w*.7),(h,w*.42)],dark)
  for zz in range(int(h)-10,int(h),4):
   rod(eid+" paint band",(x,y,zz),(x,y,zz+2),w*.45,light)
 elif kind in ("clarifier","makeup_tank"):
  o=lathe(eid,x,y,[(0,w/2),(h,w/2)],concrete if kind=="clarifier" else silver)
  ring(eid+" rim",(x,y,h),w/2,.08,steel)
  if kind=="clarifier":
   box(eid+" bridge",(x,y,h+.3),(w,.8,.25),steel)
   rod(eid+" center drive",(x,y,h),(x,y,h+1),.8,steel)
 elif kind=="stave":
  o=box(eid,(x,y,z),(w,dep,h),shell)
 elif kind=="turbine":
  o=box(eid,(x,y,z),(w,dep,h),steel)
  rod(eid+" generator",(x+4,y,z),(x+9,y,z),1.3,watermat)
 elif kind=="pump":
  o=box(eid,(x,y,z),(w,dep,h),watermat)
  rod(eid+" motor",(x,y+.5,z+.6),(x,y+2.2,z+.6),.55,steel)
 else:
  o=box(eid,(x,y,z),(w,dep,h),steel if kind=="blower" else silver)
  if kind=="air_cooler":
   for xx in (-2,2):
    ring(eid+" fan",(x+xx,y,z+h/2+.07),1.25,.10,dark)
    for a in (0,math.pi/2):beam(eid+" fan blade",(x+xx-1.1*math.cos(a),y-1.1*math.sin(a),z+h/2+.08),(x+xx+1.1*math.cos(a),y+1.1*math.sin(a),z+h/2+.08),.15,dark)
 o["equipment_id"]=eid;o["source"]=d["source"];o["geometry_basis"]=d["geometry_basis"]
 floor=3 if kind=="furnace" else .5 if kind=="scrubber" else max(0,z-h/2) if kind in ("pump","turbine","air_cooler","boiler","blower","sludge_receiver") else 0
 if floor>0:box(eid+" concrete foundation",(x,y,floor/2),(w+1,dep+1,floor),concrete)
 if kind!="stave":
  label(eid,(x,y-dep/2-.12,max(2.5,z)),.65)
# Furnace frames, catwalks with real openings, conveyors, cast houses.
current=cols["04_Structures"]
for ox in (-62,62):
 x,y=ox,18
 for dx in (-8,8):
  for dy in (-8,8):
   box("furnace concrete footing",(x+dx,y+dy,.6),(2,2,1.2),concrete)
   box("furnace main column",(x+dx,y+dy,26),(.4,.4,52),steel)
 for zz in (18.5,28,36,44,51):
  platform(x,y,zz)
  for s in (-1,1):
   beam("furnace crossbeam",(x-8,y+s*8,zz),(x+8,y+s*8,zz),.27)
   if zz<44:
    beam("diagonal bracing",(x-8,y+s*8,zz),(x+8,y+s*8,zz+7.2),.14)
    beam("diagonal bracing",(x+8,y+s*8,zz),(x-8,y+s*8,zz+7.2),.14)
 for xx in (x+9.3,x+10.05):rod("ladder stringer",(xx,y+8.5,0),(xx,y+8.5,51),.045)
 for zz in range(1,102):rod("ladder rung",(x+9.3,y+8.5,zz*.5),(x+10.05,y+8.5,zz*.5),.025)
 for zz in range(3,51,2):ring("ladder cage",(x+9.67,y+8.5,zz),.65,.025)
 for px in (-32,-20,-6,8,20,32,44):
  box("gas main support footing",(ox+px,-6,.3),(1.4,1.6,.6),concrete)
  box("gas main support",(ox+px,-6,3.8),(.22,.4,7.0),steel)
  box("gas main saddle",(ox+px,-6,7.25),(.8,1.8,.12),steel)
 # Cast house behind furnace: no unrelated pipelines through its walls.
 box("cast house",(x,53,5.5),(23,24,11),silver)
 for dx in range(-11,12,2):box("cast house corrugation",(x+dx,40.92,5.5),(.07,.1,10.8),steel)
 for s in (-1,1):
  roof=box("cast house pitched roof",(x+s*5.9,53,12.4),(12.6,25,.2),red);roof.rotation_euler.y=s*math.radians(12)
 box("stockhouse",(x,73,5),(16,13,10),silver)
 a,b=Vector((x,68,10)),Vector((x,18,50))
 for dx in (-1.8,1.8):
  beam("inclined conveyor bottom chord",a+Vector((dx,0,0)),b+Vector((dx,0,0)),.2)
  beam("inclined conveyor top chord",a+Vector((dx,0,2.4)),b+Vector((dx,0,2.4)),.16)
 for k in range(17):
  p=a.lerp(b,k/16)
  beam("conveyor deck",p+Vector((-1.8,0,0)),p+Vector((1.8,0,0)),.16)
  if k<16:
   q=a.lerp(b,(k+1)/16)
   for dx in (-1.8,1.8):beam("conveyor diagonal",p+Vector((dx,0,0)),q+Vector((dx,0,2.4)),.09)
 # Closed belt casing reaches the charging station.
 beam("conveyor belt",a,b,1.65,dark)
# Pipe geometry uses the exact same rounded centerlines checked independently.
current=cols["03_Connected_pipes"]
for l in data["lines"]:
 ps=rounded(l);r=l["radius_m"];m=colors[l["medium"]]
 o=tube(l["id"],ps,r,m)
 for k in ("id","from","to","medium","source","state"):o[k]=l[k]
 o["radius_m"]=r;o["design_basis"]="public PFD; illustrative routing"
 # Open-center flange collars: no disc blocking the pipe bore.
 for endpoint,neighbor in ((ps[0],ps[1]),(ps[-1],ps[-2])):
  dv=(Vector(neighbor)-Vector(endpoint)).normalized()
  if (Vector(neighbor)-Vector(endpoint)).length<r*.2:continue
  center=Vector(endpoint)+dv*r*.18
  axis=dv.to_track_quat("Z","Y")
  pts=[center+axis@Vector(((r+.07)*math.cos(j*math.tau/32),(r+.07)*math.sin(j*math.tau/32),0)) for j in range(33)]
  flange=tube(l["id"]+" flange",pts,max(.035,r*.08),silver);flange["parent_line"]=l["id"]
 # Valve housing and state are attached only to the stove branches.
 if any(l["id"].split("-")[1].startswith(t) for t in ("C20","H20","G20","A20","F20")):
  p=Vector(ps[len(ps)//2]);box(l["id"]+" valve actuator",p+Vector((0,0,r+.3)),(.35,.35,.4),yellow if l["state"]=="open" else dark)
  rod(l["id"]+" valve stem",p+Vector((0,0,r)),p+Vector((0,0,r+.4)),.04,steel)
# Optional direction overlay; uses the same line directions, hides closed-line arrows.
current=cols["06_Flow_arrows"]
for l in data["lines"]:
 if l["state"]!="open" or l.get("exact_polyline"):continue
 ps=rounded(l);segments=[(Vector(a),Vector(b)) for a,b in zip(ps,ps[1:])];a,b=max(segments,key=lambda ab:(ab[1]-ab[0]).length)
 if (b-a).length<2:continue
 d=(b-a).normalized();c=(a+b)/2+Vector((0,0,l["radius_m"]+.18))
 q=d.to_track_quat("Z","Y");radius=max(.16,l["radius_m"]*.5);length=max(.5,l["radius_m"]*1.8)
 vs=[c+q@Vector((radius*math.cos(t*math.tau/12),radius*math.sin(t*math.tau/12),-length/2)) for t in range(12)]+[c+d*length/2]
 me=bpy.data.meshes.new("flow arrow");me.from_pydata(vs,[],[(i,(i+1)%12,12) for i in range(12)]);me.materials.append(orange)
 ob=link(bpy.data.objects.new("FLOW "+l["id"],me));ob["line_id"]=l["id"]
cols["06_Flow_arrows"].hide_render=True;cols["06_Flow_arrows"].hide_viewport=True
# MAEK inspection station attached to BF1-W002; pressure-bearing pipe remains continuous.
current=cols["05_Inspection"]
x=-72;y=-12;z=6.5
box("Inspection platform",(x,-15,4.55),(9,3.5,.18),steel)
for dx in (-4,4):
 for yy in (-16.5,-13.5):box("Inspection platform leg",(x+dx,yy,2.3),(.12,.12,4.6),steel)
for yy in (-16.6,-13.35):
 rod("Inspection guardrail",(x-4.4,yy,5.65),(x+4.4,yy,5.65),.04,yellow)
 for dx in (-4,-2,0,2,4):rod("Inspection rail post",(x+dx,yy,4.6),(x+dx,yy,5.65),.025,yellow)
# Weathered sleeve surface, not a hole/cut in the transport line.
rod("BF1-W002 illustrative corrosion patch",(x-.7,y,z),(x+.7,y,z),.234,rust)["line_id"]="BF1-W002"
rod("UT contact probe",(x,y-.33,z),(x,y-.235,z),.075,black)
box("UT cart top",(x,-15,5.5),(1,.6,.08),steel)
for dx in (-.4,.4):
 for yy in (-15.2,-14.8):rod("UT cart leg",(x+dx,yy,4.65),(x+dx,yy,5.5),.025,steel)
box("UT meter",(x,-15,5.71),(.55,.35,.3),orange);box("UT display",(x,-15.18,5.75),(.32,.015,.15),screen)
tube("UT electrical cable",[(x,-15,5.8),(x+.5,-14.8,5.6),(x+.6,-13.5,5.8),(x,-12.33,z)],.014,black)
label("MAEK  |  BF1-W002",(x,-16.7,5.1),.36)
# Cameras and lighting.
current=cols["08_Cameras"]
def camera(name,loc,target,lens=40,ortho=None):
 ca=bpy.data.cameras.new(name);o=link(bpy.data.objects.new(name,ca));o.location=loc;o.rotation_euler=(Vector(target)-o.location).to_track_quat("-Z","Y").to_euler();ca.lens=lens;ca.clip_end=2000
 if ortho:ca.type="ORTHO";ca.ortho_scale=ortho
 return o
hero=camera("01 Overview to inspection",(180,-282,151),(0,21,20),43)
for f,loc,target,lens in [(1,(180,-282,151),(0,21,20),43),(96,(-20,-112,65),(-58,18,21),43),(168,(-82,-41,18),(-72,-6,8),45),(240,(-77,-24,9.8),(-72,-12,6.5),52)]:
 hero.location=loc;hero.rotation_euler=(Vector(target)-hero.location).to_track_quat("-Z","Y").to_euler();hero.data.lens=lens
 hero.keyframe_insert(data_path="location",frame=f);hero.keyframe_insert(data_path="rotation_euler",frame=f);hero.data.keyframe_insert(data_path="lens",frame=f)
for fc in hero.animation_data.action.fcurves:
 for k in fc.keyframe_points:k.interpolation="LINEAR"
detail=camera("02 Connected BF1",(-153,-108,79),(-57,24,24),43)
audit=camera("03 Flow routing overview",(0,-80,190),(0,17,0),40,275)
close=camera("04 MAEK inspection",(-77,-24,9.8),(-72,-12,6.5),52)
ld=bpy.data.lights.new("Daylight","SUN");sun=link(bpy.data.objects.new("Daylight",ld));ld.energy=2;ld.angle=math.radians(12);sun.rotation_euler=(math.radians(25),math.radians(-22),math.radians(-25))
world=bpy.data.worlds.new("Connected daylight");world.use_nodes=True;nt=world.node_tree;sky=nt.nodes.new("ShaderNodeTexSky");sky.sky_type="NISHITA";sky.sun_elevation=math.radians(30);sky.sun_rotation=math.radians(135);sky.sun_disc=False;nt.nodes["Background"].inputs["Strength"].default_value=.3;nt.links.new(sky.outputs[0],nt.nodes["Background"].inputs["Color"]);sc.world=world
sc.render.engine="CYCLES";sc.cycles.samples=12;sc.cycles.use_denoising=True;sc.render.resolution_x=1280;sc.render.resolution_y=720;sc.render.resolution_percentage=100;sc.render.image_settings.file_format="PNG"
sc.render.fps=24;sc.frame_start=1;sc.frame_end=240;sc.camera=hero;sc.frame_set(1)
sc["basis"]="Public PFD-inspired demonstration; not POSCO as-built/P&ID; no hydraulic solution"
sc["verified_pipe_lines"]=len(data["lines"]);sc["connectivity_report"]="connectivity_report.json"
for area in bpy.context.screen.areas if bpy.context.screen else []:
 if area.type=="VIEW_3D":area.spaces.active.region_3d.view_perspective="CAMERA"
readme=bpy.data.texts.new("READ_ME__MODEL_BASIS")
readme.write("MAEK connected piping\n236 tagged pipe segments, two illustrative process trains.\nRead MODEL_BASIS.md and connectivity_report.json beside this file.\nOld unverified geometry is archived and hidden.\nToggle 06_Flow_arrows for schematic flow directions.\nStove 1 ON_BLAST; stoves 2 and 3 ON_GAS.\nNo POSCO as-built drawing was supplied; geometry, sizes, instruments and layout are illustrative.\nNo pressure/flow/thermal/stress simulation or complete engineering P&ID.\n")
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_connected_steelworks.blend"))
# Verify the saved geometry has one visible centerline object for each network line.
for line in data["lines"]:
 ob=bpy.data.objects.get(line["id"]);assert ob and ob.type=="CURVE" and ob["from"]==line["from"]
 points=ob.data.splines[0].points
 assert (Vector(points[0].co[:3])-Vector(data["nodes"][line["from"]]["position"])).length<1e-4
 assert (Vector(points[-1].co[:3])-Vector(data["nodes"][line["to"]]["position"])).length<1e-4
print("GEOMETRY_ENDPOINTS_PASS",len(data["lines"]),flush=True)
for cam,name in [(hero,"connected_overview.png"),(detail,"connected_furnace.png"),(close,"connected_inspection.png")]:
 sc.camera=cam;sc.render.filepath=str(ROOT/name);bpy.ops.render.render(write_still=True)
sc.camera=audit;cols["06_Flow_arrows"].hide_render=False;sc.render.filepath=str(ROOT/"connected_flow_overview.png");bpy.ops.render.render(write_still=True)
print("BUILD_AND_RENDER_COMPLETE",flush=True)
