import bpy, math, random
from mathutils import Vector
random.seed(11)
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
def mat(n,c,metal=0,rough=.5):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*c,1); p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough; return m
steel=mat('Steel structure',(.15,.18,.19),.75); silver=mat('Insulation cladding',(.48,.51,.50),.65,.38); rust=mat('Surface corrosion',(.29,.095,.035),.35,.85); dark=mat('Concrete',(.15,.16,.155),0,.92); yellow=mat('Safety yellow',(.8,.48,.025),.2); red=mat('Valve red',(.48,.06,.035),.4); pipe=mat('Painted steel',(.19,.24,.24),.65)
def cube(n,loc,scale,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc); o=bpy.context.object; o.name=n; o.dimensions=scale; bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); o.data.materials.append(m); return o
def cyl(n,a,b,r,m):
 d=Vector(b)-Vector(a); mid=(Vector(a)+Vector(b))/2; bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=r,depth=d.length,location=mid); o=bpy.context.object; o.name=n; o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); o.data.materials.append(m); return o
cube('Floor',(0,0,-.18),(20,13,.36),dark); cube('Back wall',(0,4.8,4.5),(20,.3,9),dark)
for x in (-8,-4,0,4,8):
 cube('Steel column',(x,4.3,4.5),(.35,.4,9),steel); cube('Pipe support post',(x,1,2),(.2,.2,4),steel); cube('Pipe support crossbeam',(x,1,3.45),(.22,4.4,.2),steel)
for z in (3.65,5.6,8): cube('Wall beam',(0,4.35,z),(20,.2,.25),steel)
for y,z,r,m,n in [(-.4,3.8,.40,silver,'Insulated steam'),(.65,4.0,.30,pipe,'Process pipe'),(1.5,3.9,.26,silver,'Insulated return'),(2.3,4.05,.22,pipe,'Utility pipe')]:
 cyl(n,(-9,y,z),(9,y,z),r,m)
 for x in (-7,-5,-3,-1,1,3,5,7): cyl('Cladding joint',(x-.035,y,z),(x+.035,y,z),r*1.015,steel)
for x in (-5,4):
 cyl('Vertical riser',(x,2.3,1),(x,2.3,4.05),.22,pipe)
 cyl('Valve body',(x-.23,2.3,4.05),(x+.23,2.3,4.05),.34,steel)
 cyl('Valve stem',(x,2.3,4.33),(x,2.3,4.85),.045,steel)
 bpy.ops.mesh.primitive_torus_add(major_radius=.27,minor_radius=.035,location=(x,2.3,4.85)); bpy.context.object.name='Valve handwheel'; bpy.context.object.data.materials.append(red)
for i in range(18):
 x=random.uniform(-3.1,-1.5); a=random.uniform(2.9,4.9); y=.65+math.cos(a)*.305; z=4+math.sin(a)*.305
 bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=6,radius=1,location=(x,y,z)); o=bpy.context.object; o.name='Visible corrosion illustration'; o.scale=(random.uniform(.07,.16),.035,random.uniform(.05,.1)); o.data.materials.append(rust)
for x in (-8,-4,0,4,8): cube('Walkway stripe',(x,-3,.015),(2.6,.09,.025),yellow)
for y in (-2.4,-4.4):
 cyl('Guardrail',(-9,y,1.2),(9,y,1.2),.035,yellow)
 for x in (-8,-4,0,4,8): cyl('Guardrail post',(x,y,0),(x,y,1.2),.035,yellow)
world=bpy.context.scene.world; world.color=(.12,.12,.12)
def area(loc,power,size):
 bpy.ops.object.light_add(type='AREA',location=loc); o=bpy.context.object; o.data.energy=power; o.data.shape='DISK'; o.data.size=size; o.rotation_euler=(Vector((0,1,3))-o.location).to_track_quat('-Z','Y').to_euler()
area((0,-3,8),1800,8); area((-7,1,7),900,5); area((7,1,7),900,5)
bpy.ops.object.camera_add(location=(11,-14,7)); cam=bpy.context.object; cam.rotation_euler=(Vector((0,.7,3.2))-cam.location).to_track_quat('-Z','Y').to_euler(); cam.data.lens=34; bpy.context.scene.camera=cam
sc=bpy.context.scene; sc.render.engine='CYCLES'; sc.cycles.samples=24; sc.render.resolution_x=1280; sc.render.resolution_y=720; sc.render.resolution_percentage=100; sc.view_settings.view_transform='AgX'; sc.render.image_settings.file_format='PNG'; sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/pipe_scene_preview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_pipe_environment.blend'); bpy.ops.render.render(write_still=True)
