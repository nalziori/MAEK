import bpy, math, random
from mathutils import Vector
random.seed(61)
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_steelworks_exterior.blend')
def mat(n,c,metal=0,rough=.6):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*c,1); p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough; return m
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
def path(n,pts,r,m):
 c=bpy.data.curves.new(n,'CURVE'); c.dimensions='3D'; c.resolution_u=8; c.bevel_depth=r; c.bevel_resolution=3; s=c.splines.new('POLY'); s.points.add(len(pts)-1)
 for p,pt in zip(s.points,pts): p.co=(*pt,1)
 o=bpy.data.objects.new(n,c); bpy.context.collection.objects.link(o); o.data.materials.append(m); return o
steel=bpy.data.materials['Steel structure']; pipe=bpy.data.materials['Painted steel']; silver=bpy.data.materials['Insulation cladding']; furnace=bpy.data.materials['Furnace aged red brown']; wall=bpy.data.materials['Factory corrugated grey']; roof=bpy.data.materials['Weathered roof']; concrete=bpy.data.materials['Site concrete']; asphalt=bpy.data.materials['Asphalt']; yellow=bpy.data.materials['Safety yellow']
blue=mat('Blue grey service pipe',(.14,.21,.23),.6); brown=mat('Oxidised process piping',(.24,.12,.08),.6); oxide=mat('Weathered orange steel',(.31,.16,.09),.5); cream=mat('Aged insulation jacket',(.41,.41,.36),.5)
# Expand ground and long mill buildings beyond the initial scene.
cube('Expanded plant pad',(0,15,-.67),(360,280,.35),concrete)
for x,y,w,d,h in [(-105,31,64,25,16),(105,31,65,25,17),(-97,84,72,28,15),(0,91,80,30,16),(99,88,75,32,18),(-110,-3,35,18,11),(113,-2,35,18,12)]:
 cube('Rolling and service hall',(x,y,h/2),(w,d,h),wall); cube('Hall roof',(x,y,h+.3),(w+1,d+1,.6),roof)
 for xx in range(int(x-w/2+4),int(x+w/2),7): cube('Hall facade rib',(xx,y-d/2-.15,h/2),(.16,.2,h),steel)
for x in (-120,-70,-20,30,80,130): cube('Long plant roadway',(x,65,-.12),(30,8,.12),asphalt)
# Three multi-level pipe corridors, with distinct large and small services.
for rack_y in (-20,59,115):
 for x in range(-140,141,14):
  for y in (rack_y-5,rack_y+5): cube('Pipe bridge steel column',(x,y,6.0),(.36,.36,12),steel)
  for z in (5.4,8.2,11): cube('Pipe bridge crossbeam',(x,rack_y,z),(.34,10.8,.28),steel)
 for tier in range(3):
  z=5.75+tier*2.8
  for i in range(9):
   y=rack_y-4.3+i*1.04; radius=[.62,.48,.38,.27,.22,.18,.32,.24,.2][i] if tier==0 else [.40,.28,.21,.18,.34,.24,.18,.3,.22][i]
   material=[furnace,brown,silver,blue,pipe,cream,steel,silver,pipe][(i+tier)%9]
   cyl('Long process line',(-140,y,z),(140,y,z),radius,material)
   for x in range(-126,127,28): cyl('Expansion joint band',(x-.09,y,z),(x+.09,y,z),radius*1.07,steel)
# Branch lines toward central buildings, each supported by portal frames.
for bx in (-118,-84,-50,-16,24,60,96,130):
 for y in range(-5,111,16):
  for x in (bx-2,bx+2): cube('Branch rack column',(x,y,3.7),(.25,.25,7.4),steel)
  cube('Branch rack support',(bx,y,7.1),(4.5,.25,.22),steel)
 for j in range(5):
  x=bx-1.5+j*.75; z=7.45+(j%2)*.5; cyl('Branch pipe',(x,-8,z),(x,112,z),(.18,.24,.32,.22,.14)[j],[pipe,silver,brown,blue,cream][j])
# A clearly visible steam expansion loop like the Scunthorpe reference.
for x in (-46,31,84):
 y=-24.3; z=5.75; R=1.2; pts=[]
 pts.append((x-3,y,z))
 for j in range(13):
  t=math.pi/2*j/12; pts.append((x-3+R*math.sin(t),y,z-R*(1-math.cos(t))))
 pts.append((x-1.8,y,z-3.6))
 for j in range(13):
  t=math.pi/2*j/12; pts.append((x-0.6-R*math.cos(t),y,z-3.6-R*math.sin(t)))
 pts.append((x+.6,y,z-4.8))
 for j in range(13):
  t=math.pi/2*j/12; pts.append((x+.6+R*math.sin(t),y,z-3.6-R*math.cos(t)))
 pts.append((x+1.8,y,z-1.2))
 for j in range(13):
  t=math.pi/2*j/12; pts.append((x+3-R*math.cos(t),y,z-1.2+R*math.sin(t)))
 pts.append((x+3.5,y,z)); path('Steam expansion loop',pts,.25,silver)
# Tanks and towers add depth to the larger layout.
for x,y,r,h in [(-126,68,9,15),(-107,68,8,13),(119,61,10,18),(137,62,7,14),(-124,119,8,13),(122,118,10,15)]:
 cyl('Gas holder',(x,y,0),(x,y,h),r,wall); cyl('Gas holder roof',(x,y,h),(x,y,h+.5),r+.3,roof)
for x in (-78,72,123):
 cyl('Tall exhaust stack',(x,82,0),(x,82,40),1.2,steel)
 for z in (12,24,36): cyl('Stack support band',(x,82,z-.12),(x,82,z+.12),1.4,steel)
# More prominent plant-wide camera view; keep the existing inspection close-up.
cam=bpy.context.scene.camera; cam.animation_data_clear(); cam.data.lens=33
for f,loc,target in [(1,(142,-184,100),(0,34,9)),(70,(90,-130,65),(0,30,9)),(150,(26,-55,23),(-2,8,6)),(210,(11,-23,10),(-1,0,4)),(300,(5,-10,5.7),(-1.5,-.4,3.8))]:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
for fc in cam.animation_data.action.fcurves:
 for k in fc.keyframe_points: k.interpolation='BEZIER'
sc=bpy.context.scene; sc.frame_start=1; sc.frame_end=300; sc.render.fps=24; sc.cycles.samples=8; sc.cycles.use_denoising=True; sc.frame_set(1); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_large_overview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_steelworks_large.blend'); bpy.ops.render.render(write_still=True)
sc.frame_set(210); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_large_approach.png'; bpy.ops.render.render(write_still=True)

