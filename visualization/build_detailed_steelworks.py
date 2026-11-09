import bpy, math, random
from mathutils import Vector
random.seed(9)
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_day_furnaces.blend')
steel=bpy.data.materials['Steel structure']; furnace=bpy.data.materials['Furnace aged red brown']; silver=bpy.data.materials['Insulation cladding']; yellow=bpy.data.materials['Safety yellow']
def mat(n,c,metal=.3,rough=.7):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes['Principled BSDF']; p.inputs['Base Color'].default_value=(*c,1); p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough; return m
blue=mat('Weathered blue steel',(.12,.20,.23),.65); orange=mat('Aged rust and red primer',(.34,.15,.075),.5); concrete=mat('Structure concrete',(.35,.34,.30)); glass=mat('Dark industrial glass',(.1,.17,.18),.4); tan=mat('Light metal housing',(.40,.37,.31),.5); foliage=mat('Leaf foliage',(.09,.18,.07),0,.9)
cache={}
def mesh(kind,m):
 key=(kind,m.name)
 if key in cache:return cache[key]
 me=bpy.data.meshes.new(kind+' '+m.name)
 if kind=='box':
  vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]; faces=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
 else:
  N=24; vs=[(math.cos(i*math.tau/N),math.sin(i*math.tau/N),z) for z in (-.5,.5) for i in range(N)]; faces=[tuple(reversed(range(N))),tuple(range(N,2*N))]+[(i,(i+1)%N,(i+1)%N+N,i+N) for i in range(N)]
 me.from_pydata(vs,[],faces); me.materials.append(m)
 if kind=='cylinder':
  for p in me.polygons:
   if len(p.vertices)==4:p.use_smooth=True
 cache[key]=me; return me
def box(n,loc,dim,m):
 o=bpy.data.objects.new(n,mesh('box',m)); bpy.context.collection.objects.link(o); o.location=loc; o.scale=dim; return o
def rod(n,a,b,r,m):
 d=Vector(b)-Vector(a); o=bpy.data.objects.new(n,mesh('cylinder',m)); bpy.context.collection.objects.link(o); o.location=(Vector(a)+Vector(b))/2; o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); o.scale=(r,r,d.length); return o
def beam(n,a,b,w,m):
 d=Vector(b)-Vector(a); o=box(n,(Vector(a)+Vector(b))/2,(w,w,d.length),m); o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); return o
def pipepath(n,pts,r,m):
 cu=bpy.data.curves.new(n,'CURVE'); cu.dimensions='3D'; cu.bevel_depth=r; cu.bevel_resolution=3; s=cu.splines.new('BEZIER'); s.bezier_points.add(len(pts)-1)
 for p,co in zip(s.bezier_points,pts):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
 o=bpy.data.objects.new(n,cu); bpy.context.collection.objects.link(o); cu.materials.append(m);return o
# Two non-identical process towers with walkways, bracing, ladders, charging structures, and pipe connections.
for x,y,S in [(-50,5,1),(24,25,.82)]:
 for dx in (-5.5,-3,0,3,5.5):
  for dy in (-6.5,6.5):box('Vertical furnace framework',(x+dx,y+dy,23),(.24,.24,38),blue)
 for z in (11,16,22,28,34,40,46):
  box('Maintenance platform',(x,y,z),(15.2,15,.28),steel)
  for side in (-1,1):
   rod('Platform safety rail',(x-7.5,y+side*7.3,z+1.25),(x+7.5,y+side*7.3,z+1.25),.045,yellow)
   rod('Platform side rail',(x+side*7.4,y-7.3,z+1.25),(x+side*7.4,y+7.3,z+1.25),.045,yellow)
   for dx in (-7.4,-4.5,-1.5,1.5,4.5,7.4): rod('Rail post',(x+dx,y+side*7.3,z+.1),(x+dx,y+side*7.3,z+1.25),.035,yellow)
 for z in (11,20,29,38):
  for side in (-1,1):
   beam('Diagonal steel bracing',(x-7,y+side*7,z),(x+7,y+side*7,z+8),.14,blue); beam('Diagonal steel bracing',(x+7,y+side*7,z),(x-7,y+side*7,z+8),.14,blue)
 # Ladder with cage hoops represented by horizontal rungs.
 for dx in (5.1,6.0):rod('Access ladder rail',(x+dx,y-7.65,7),(x+dx,y-7.65,47),.055,steel)
 for z in range(8,47):rod('Access ladder rung',(x+5.1,y-7.65,z),(x+6,y-7.65,z),.035,steel)
 rod('Upper charging vessel',(x,y,43),(x,y,52),1.75,blue)
 for dx in (-2.5,2.5):
  for dy in (-2.5,2.5):rod('Charging tower post',(x+dx,y+dy,43),(x+dx,y+dy,53),.12,steel)
 for z in (48,52.5):
  for dy in (-2.5,2.5):rod('Charging tower railing',(x-2.5,y+dy,z),(x+2.5,y+dy,z),.08,steel)
 # Bustle main and several tuyere branches, visual interpretation only.
 pts=[(x+5*math.cos(t),y+5*math.sin(t),13) for t in [2*math.pi*i/48 for i in range(49)]]
 for a,b in zip(pts,pts[1:]):rod('Circular hot blast main',a,b,.45,orange)
 for i in range(12):
  a=i*math.tau/12; rod('Tuyere connection',(x+5*math.cos(a),y+5*math.sin(a),13),(x+3.6*math.cos(a),y+3.6*math.sin(a),10.8),.18,steel)
 for dx in (-3,0,3):pipepath('Vertical cooling pipe',[(x+dx,y-5,11),(x+dx,y-6,21),(x+dx,y-6,34),(x+dx+1,y-5,41)],.12,silver)
 # Control cabins and hoppers break up the silhouette.
 box('Furnace operator cabin',(x+7,y-1,28),(4.8,5,3),tan);box('Furnace cabin windows',(x+7,y-3.55,28.3),(4,.06,1),glass)
 rod('Dust collector vessel',(x-19,y+10,3),(x-19,y+10,20),3.3,blue)
 pipepath('Dust collector connection',[(x-1,y+3,42),(x-10,y+6,38),(x-15,y+8,25),(x-19,y+10,20)],1.15,steel)
# Overhead conveyor support trusses, intermediate hoppers and pipe bridge connections.
for x in (-95,-78,-13,8,45,72):
 for dy in (-2,2):box('Conveyor support post',(x,8+dy,8),(.22,.22,16),steel)
 for z in (5,10,15):box('Conveyor support crossbeam',(x,8,z),(.24,4.5,.24),steel)
for x in (-80,-10,50):
 box('Conveyor transfer building',(x,8,16),(7,8,5),tan)
 for dx in (-3,3):
  for dy in (-3,3):box('Transfer support',(x+dx,8+dy,7),(.28,.28,14),steel)
# Replace boxy green markers with loosely clustered vegetation.
for o in list(bpy.data.objects):
 if o.name.startswith('Distant trees'):bpy.data.objects.remove(o,do_unlink=True)
for i in range(100):
 x=-160+i*3.4; y=-35+random.uniform(-2,2); h=random.uniform(1.7,4); rod('Tree trunk',(x,y,0),(x,y,h*.55),.12,steel)
 # Shared low-poly crowns.
 for dx,dy in ((0,0),(1,.4),(-.8,-.5)):
  o=box('Tree canopy',(x+dx,y+dy,h*.75),(2.5,2.5,h*.65),foliage);o.rotation_euler.z=random.random()
# Dedicated close inspection camera, preserving the existing animated camera.
camdata=bpy.data.cameras.new('Furnace close camera'); cam=bpy.data.objects.new('Furnace close camera',camdata); bpy.context.collection.objects.link(cam);cam.location=(-10,-83,38);cam.rotation_euler=(Vector((-39,10,25))-cam.location).to_track_quat('-Z','Y').to_euler();camdata.lens=45
sc=bpy.context.scene; original=sc.camera; sc.cycles.samples=8;sc.cycles.use_denoising=True;sc.frame_set(1);sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_detail_wide.png';bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_steelworks_detailed.blend');bpy.ops.render.render(write_still=True)
sc.camera=cam;sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_detail_furnace.png';bpy.ops.render.render(write_still=True)
