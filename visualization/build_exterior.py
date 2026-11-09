import bpy, math, random
from mathutils import Vector
random.seed(19)
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_pipe_environment_detail.blend')
def mat(n,c,metal=0,rough=.65):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*c,1); p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough; return m
def cube(n,loc,dim,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc); o=bpy.context.object; o.name=n; o.dimensions=dim; bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); o.data.materials.append(m); return o
def cyl(n,a,b,r,m,verts=32):
 d=Vector(b)-Vector(a); bpy.ops.mesh.primitive_cylinder_add(vertices=verts,radius=r,depth=d.length,location=(Vector(a)+Vector(b))/2); o=bpy.context.object; o.name=n; o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); o.data.materials.append(m); bpy.ops.object.shade_smooth(); return o
def cone(n,loc,r1,r2,depth,m):
 bpy.ops.mesh.primitive_cone_add(vertices=48,radius1=r1,radius2=r2,depth=depth,location=loc); o=bpy.context.object; o.name=n; o.data.materials.append(m); bpy.ops.object.shade_smooth(); return o
steel=bpy.data.materials['Steel structure']; pipe=bpy.data.materials['Painted steel']; silver=bpy.data.materials['Insulation cladding']; yellow=bpy.data.materials['Safety yellow']; red=bpy.data.materials['Valve red']
wall=mat('Factory corrugated grey',(.24,.27,.27),.35); roof=mat('Weathered roof',(.15,.18,.19),.5); asphalt=mat('Asphalt',(.095,.105,.10),0,.98); concrete=mat('Site concrete',(.24,.25,.23),0,.95); furnace=mat('Furnace aged red brown',(.25,.105,.065),.6,.8); pale=mat('Site road lines',(.66,.61,.39),0,.8); glass=mat('Factory windows',(.105,.16,.18),.35,.3)
# The existing inspection area sits at the near facade of the central works building.
cube('Site ground',(0,8,-.43),(210,170,.45),concrete); cube('Road',(0,-17,-.17),(165,12,.09),asphalt)
for x in range(-72,73,12): cube('Road centre marking',(x,-17,-.11),(6,.18,.025),pale)
cube('Main steelworks hall',(0,18,9),(70,26,18),wall); cube('Main hall roof',(0,18,18.2),(71,27,.55),roof)
for x in range(-33,34,3): cube('Facade vertical rib',(x,4.85,9),(.13,.24,17.8),steel)
for x in (-27,-19,-11,13,21,29):
 cube('Industrial high window',(x,4.68,13.4),(5,.08,2.2),glass)
 for z in (12.65,13.4,14.15): cube('Window frame',(x,4.60,z),(5,.08,.08),steel)
for x in (-27,22):
 cube('Loading bay',(x,4.62,4.8),(9,.12,8.5),roof)
 for z in range(1,9): cube('Loading bay panel',(x,4.52,z),(9,.08,.07),wall)
for x,y,sx,sy,h in [(-55,25,30,22,12),(57,24,33,22,13),(48,52,42,22,10),(-55,57,36,25,13)]:
 cube('Auxiliary industrial building',(x,y,h/2),(sx,sy,h),wall); cube('Auxiliary roof',(x,y,h+.25),(sx+1,sy+1,.5),roof)
 for xx in range(int(x-sx/2+3),int(x+sx/2),5): cube('Auxiliary wall rib',(xx,y-sy/2-.12,h/2),(.12,.15,h),steel)
# Simplified blast furnace and stoves inspired by industrial reference, not a surveyed replica.
fx,fy=-42,37
cyl('Blast furnace lower shell',(fx,fy,4),(fx,fy,16),5.3,furnace); cone('Blast furnace bosh',(fx,fy,18),5.3,3.2,4,furnace); cyl('Blast furnace shaft',(fx,fy,20),(fx,fy,33),3.2,furnace); cone('Furnace top',(fx,fy,34),3.2,2.1,2,steel)
for z in (9,15,22,29,33):
 bpy.ops.mesh.primitive_torus_add(major_radius=(5.4 if z<18 else 3.3),minor_radius=.15,location=(fx,fy,z)); bpy.context.object.name='Furnace service ring'; bpy.context.object.data.materials.append(steel)
for dx in (-6,6):
 for dy in (-6,6): cube('Furnace tower column',(fx+dx,fy+dy,18),(.42,.42,36),steel)
for z in (9,17,25,34):
 for dy in (-6,6): cube('Furnace platform beam',(fx,fy+dy,z),(13,.35,.35),steel)
 for dx in (-6,6): cube('Furnace crossbeam',(fx+dx,fy,z),(.35,13,.35),steel)
for x in (-27,-18,-9):
 cyl('Hot blast stove',(x,46,1),(x,46,25),3.0,furnace); cone('Stove cap',(x,46,26),3,1.1,2,steel); cyl('Stove stack',(x,46,26),(x,46,36),.8,steel)
for x,y,h in [(26,35,42),(35,36,49),(63,34,37)]:
 cone('Industrial chimney',(x,y,h/2),1.7,1.05,h,steel); cyl('Chimney rim',(x,y,h-.25),(x,y,h+.25),1.15,steel)
# Elevated pipelines link distant plant to the foreground inspection corridor.
for x in (-65,-50,-35,-20,-5,10,25,40,55,70):
 for y in (-8,0): cube('Exterior pipe rack upright',(x,y,3.15),(.27,.27,6.3),steel)
 cube('Exterior pipe rack crossbeam',(x,-4,6.15),(.3,8.5,.28),steel)
for y,z,r,m in [(-7,6.6,.55,furnace),(-5.7,6.55,.45,pipe),(-4.5,6.55,.34,silver),(-3.5,6.5,.28,pipe),(-2.6,6.5,.23,silver)]:
 cyl('Exterior overhead process pipe',(-70,y,z),(70,y,z),r,m)
 for x in range(-60,61,10): cyl('Exterior pipe joint',(x-.06,y,z),(x+.06,y,z),r*1.08,steel)
# Keep the inspection corridor visible and create a simple utility yard.
for x,y,r in [(51,1,4.5),(62,1,3.5)]:
 cyl('Storage tank',(x,y,.2),(x,y,9),r,wall); cone('Tank roof',(x,y,9.6),r,.3,1.2,roof)
for x in (-25,-15,15,25): cyl('Facade utility pipe',(x,4.35,1),(x,4.35,8),.17,pipe)
# Daylight plus lights from original close-up scene.
world=bpy.context.scene.world; world.use_nodes=True; world.node_tree.nodes['Background'].inputs['Color'].default_value=(.48,.57,.65,1); world.node_tree.nodes['Background'].inputs['Strength'].default_value=.6
bpy.ops.object.light_add(type='SUN',location=(0,-20,40)); sun=bpy.context.object; sun.name='Overcast daylight'; sun.data.energy=2; sun.rotation_euler=(math.radians(28),math.radians(-25),math.radians(-35))
cam=bpy.context.scene.camera; cam.name='Overview to inspection camera'; cam.data.lens=34
# Camera stays outside, advancing towards inspection area; targets evolve with the position.
for frame,loc,target in [(1,(80,-110,65),(0,23,13)),(70,(42,-66,35),(-2,18,11)),(150,(19,-32,15),(-1,4,5)),(240,(5,-10,5.7),(-1.5,-.4,3.8))]:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=frame); cam.keyframe_insert(data_path='rotation_euler',frame=frame)
if cam.animation_data:
 for fc in cam.animation_data.action.fcurves:
  for k in fc.keyframe_points: k.interpolation='BEZIER'
sc=bpy.context.scene; sc.frame_start=1; sc.frame_end=240; sc.render.fps=24; sc.render.engine='CYCLES'; sc.cycles.samples=12; sc.cycles.use_denoising=True; sc.render.resolution_x=1280; sc.render.resolution_y=720; sc.render.resolution_percentage=100; sc.render.image_settings.file_format='PNG'
sc.frame_set(1); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_overview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_steelworks_exterior.blend'); bpy.ops.render.render(write_still=True)
sc.frame_set(240); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_inspection.png'; bpy.ops.render.render(write_still=True)
