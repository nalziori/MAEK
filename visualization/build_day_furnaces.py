import bpy, math
from mathutils import Vector
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_furnaces_dusk.blend')
steel=bpy.data.materials['Steel structure']; red=bpy.data.materials['Furnace aged red brown']; yellow=bpy.data.materials['Safety yellow']
def material(n,c):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes['Principled BSDF']; p.inputs['Base Color'].default_value=(*c,1); p.inputs['Metallic'].default_value=.45; p.inputs['Roughness'].default_value=.6; return m
blue=material('Reference blue structure',(.16,.23,.25)); ochre=material('Reference orange roof',(.49,.20,.095)); foliage=material('Foreground greenery',(.055,.14,.055))
def cube(n,loc,dim,m):
 me=bpy.data.meshes.new(n); vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]; me.from_pydata(vs,[],[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]); me.materials.append(m); ob=bpy.data.objects.new(n,me); bpy.context.collection.objects.link(ob); ob.location=loc; ob.scale=dim; return ob
def curve(n,pts,r,m):
 c=bpy.data.curves.new(n,'CURVE'); c.dimensions='3D'; c.resolution_u=16; c.bevel_depth=r; c.bevel_resolution=4; s=c.splines.new('BEZIER'); s.bezier_points.add(len(pts)-1)
 for p,co in zip(s.bezier_points,pts): p.co=co; p.handle_left_type='AUTO'; p.handle_right_type='AUTO'
 o=bpy.data.objects.new(n,c); bpy.context.collection.objects.link(o); c.materials.append(m); return o
# Thick overhead process ducts silhouette the furnace, as in the attached photograph.
for x,y,scale in [(-50,5,1),(24,25,.8)]:
 curve('Blast furnace curved downcomer',[(x-1,y+2,43),(x-7,y+2,41),(x-12,y+2,30),(x-17,y+2,20),(x-23,y+2,16)],1.15*scale,blue)
 curve('Furnace secondary duct',[(x+1,y+3,40),(x+7,y+3,38),(x+12,y+3,28),(x+17,y+3,20)],.85*scale,steel)
 for z in (11,20,29,38):
  for dx in (-5.3,5.3): cube('Additional furnace cross brace',(x+dx,y-7,z),(.26,.3,7.5),steel)
for x in (-100,-70,0,38,80): cube('Red roof building',(x,2,7),(24,14,2),ochre)
# Daytime blue world; supplied photograph is daylight.
w=bpy.context.scene.world; w.use_nodes=True; w.node_tree.nodes['Background'].inputs['Color'].default_value=(.46,.65,.82,1); w.node_tree.nodes['Background'].inputs['Strength'].default_value=.7
sun=bpy.data.objects.get('Overcast daylight')
if sun: sun.data.energy=2.3; sun.data.color=(1,.94,.84)
# Small foreground vegetation as context, while keeping the pipe rack visible.
for i in range(45):
 x=-170+i*7.5; h=1.5+(i%4)*.45; cube('Distant trees',(x,-35,h/2), (5,4,h),foliage)
cam=bpy.context.scene.camera; cam.animation_data_clear(); cam.data.lens=36
for f,loc,target in [(1,(25,-200,42),(-18,12,20)),(110,(8,-135,39),(-18,10,20)),(190,(-5,-65,28),(-20,6,14)),(275,(1,-12,16),(-1.4,-.4,3.8)),(360,(5,-10,5.7),(-1.5,-.4,3.8))]:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
for fc in cam.animation_data.action.fcurves:
 for k in fc.keyframe_points:k.interpolation='LINEAR'
sc=bpy.context.scene; sc.frame_set(1); sc.cycles.samples=6; sc.cycles.use_denoising=True; sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_day_reference.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_day_furnaces.blend'); bpy.ops.render.render(write_still=True)
