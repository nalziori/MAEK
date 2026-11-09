import bpy, math
from mathutils import Vector
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_posco_inspired.blend')
steel=bpy.data.materials['Steel structure']; oxid=bpy.data.materials['Furnace aged red brown']; silver=bpy.data.materials['Insulation cladding']; yellow=bpy.data.materials['Safety yellow']
def mat(n,c):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(*c,1); return m
blue=mat('Furnace plant faded blue',(.18,.33,.37)); wall=mat('Cast house tan',(.42,.37,.29))
mesh_cache={}
def getmesh(kind,m):
 key=(kind,m.name)
 if key in mesh_cache: return mesh_cache[key]
 mesh=bpy.data.meshes.new(kind+' '+m.name)
 if kind=='box':
  vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]; fs=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
 else:
  N=24; vs=[(math.cos(i*math.tau/N),math.sin(i*math.tau/N),z) for z in (-.5,.5) for i in range(N)]; fs=[tuple(reversed(range(N))),tuple(range(N,2*N))]+[(i,(i+1)%N,(i+1)%N+N,i+N) for i in range(N)]
 mesh.from_pydata(vs,[],fs); mesh.materials.append(m)
 if kind=='cylinder':
  for p in mesh.polygons:
   if len(p.vertices)==4: p.use_smooth=True
 mesh_cache[key]=mesh; return mesh
def cube(n,loc,dim,m):
 o=bpy.data.objects.new(n,getmesh('box',m)); bpy.context.collection.objects.link(o); o.location=loc; o.scale=dim; return o
def cyl(n,a,b,r,m):
 d=Vector(b)-Vector(a); o=bpy.data.objects.new(n,getmesh('cylinder',m)); bpy.context.collection.objects.link(o); o.location=(Vector(a)+Vector(b))/2; o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); o.scale=(r,r,d.length); return o
def box(n,p,d,m): return cube(n,p,d,m)
def rod(n,a,b,r,m): return cyl(n,a,b,r,m)
def beam(n,a,b,w,m):
 v=Vector(b)-Vector(a); o=box(n,(Vector(a)+Vector(b))/2,(w,w,v.length),m); o.rotation_euler=v.to_track_quat('Z','Y').to_euler(); return o
# Distinct landmark beside the hall: reference-inspired geometry, not a measured replica.
x,y=-50,5
rod('Blast furnace hearth',(x,y,4),(x,y,17),5.2,oxid)
bpy.ops.mesh.primitive_cone_add(vertices=40,radius1=5.2,radius2=3.8,depth=5,location=(x,y,19.5)); bpy.context.object.name='Blast furnace bosh'; bpy.context.object.data.materials.append(oxid)
rod('Blast furnace shaft',(x,y,22),(x,y,39),3.8,oxid); rod('Charging throat',(x,y,39),(x,y,46),2.3,steel)
for dx in (-7,7):
 for dy in (-7,7): box('Furnace tower column',(x+dx,y+dy,25),(.48,.48,50),steel)
for z in (8,17,26,35,44,50):
 box('Furnace platform',(x,y,z),(16,16,.35),steel)
 for dx in (-7.5,7.5):
  box('Tower cross girder',(x+dx,y,z),(.34,15,.42),steel)
  for dy in (-7.5,7.5): rod('Platform rail upright',(x+dx,y+dy,z+.2),(x+dx,y+dy,z+1.5),.07,yellow)
 for dy in (-7.5,7.5):
  box('Tower horizontal girder',(x,y+dy,z),(15,.34,.42),steel)
  rod('Platform guardrail',(x-7.5,y+dy,z+1.5),(x+7.5,y+dy,z+1.5),.055,yellow)
for z in (8,17,26,35,44):
 for dy in (-7,7):
  beam('Tower diagonal brace',(x-7,y+dy,z),(x+7,y+dy,z+9),.18,steel); beam('Tower diagonal brace',(x+7,y+dy,z),(x-7,y+dy,z+9),.18,steel)
# Inclined raw material conveyor, as in the provided photograph.
a=Vector((-100,5,12)); b=Vector((x,5,42)); direction=(b-a).normalized(); side=Vector((0,1,0))
for yy in (-2.4,2.4): beam('Inclined conveyor side beam',a+side*yy,b+side*yy,.36,steel)
for k in range(17):
 t=k/16; center=a.lerp(b,t); beam('Conveyor cross tie',center+side*-2.4,center+side*2.4,.18,steel)
 if k<16:
  nxt=a.lerp(b,(k+1)/16)
  for yy in (-2.4,2.4): beam('Conveyor truss brace',center+side*yy,nxt+side*yy+Vector((0,0,2)),.10,steel)
for yy in (-2.4,2.4): beam('Conveyor upper rail',a+side*yy+Vector((0,0,2)),b+side*yy+Vector((0,0,2)),.12,steel)
# Stockhouse, dust catcher, gas downcomer and fan-out pipework.
box('Furnace cast house',(x+14,y+2,6),(19,20,12),wall); rod('Dust catcher',(x-17,y+11,2),(x-17,y+11,19),3.5,blue)
rod('Large downcomer',(x-4,y+3,40),(x-14,y+9,22),1.35,steel); rod('Dust catcher inlet',(x-14,y+9,22),(x-17,y+11,19),1.35,steel)
for z in (10,13,16): rod('Furnace service pipe',(x-6,y-7,z),(x+13,y-7,z),.45,silver)
cam=bpy.context.scene.camera; cam.animation_data_clear(); cam.data.lens=35
for f,loc,target in [(1,(34,-155,75),(-37,15,20)),(80,(7,-108,58),(-40,12,20)),(160,(-8,-59,35),(-45,5,20)),(225,(-10,-32,23),(-20,1,10)),(275,(1,-12,16),(-1.4,-.4,3.8)),(360,(5,-10,5.7),(-1.5,-.4,3.8))]:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
for fc in cam.animation_data.action.fcurves:
 for k in fc.keyframe_points: k.interpolation='LINEAR'
sc=bpy.context.scene; sc.cycles.samples=6; sc.cycles.use_denoising=True; sc.frame_set(80); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/blast_furnace_preview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_blast_furnace.blend'); bpy.ops.render.render(write_still=True)
