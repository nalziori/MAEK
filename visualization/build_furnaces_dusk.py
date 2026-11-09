import bpy, math
from mathutils import Vector
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_blast_furnace.blend')
# Duplicate the previously built landmark as linked geometry, giving the plant a second furnace.
prefix=('Blast furnace hearth','Blast furnace bosh','Blast furnace shaft','Charging throat','Furnace tower column','Furnace platform','Tower cross girder','Tower horizontal girder','Tower diagonal brace','Platform rail upright','Platform guardrail','Dust catcher','Large downcomer','Dust catcher inlet','Furnace service pipe','Inclined conveyor side beam','Conveyor cross tie','Conveyor truss brace','Conveyor upper rail')
original=[o for o in bpy.data.objects if o.name.startswith(prefix)]
for o in original:
 copy=o.copy(); copy.data=o.data; bpy.context.collection.objects.link(copy); copy.name='Second furnace '+o.name; copy.location.x+=74; copy.location.y+=20
# Gabled industrial halls across the front, with luminous window bands.
def mat(n,c,emission=0):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*c,1)
 if emission: p.inputs['Emission Color'].default_value=(*c,1); p.inputs['Emission Strength'].default_value=emission
 return m
roof=mat('Gabled hall metal',(.29,.32,.31)); light=mat('Industrial window lights',(.9,.74,.46),1.8)
def box(n,loc,dim,m):
 me=bpy.data.meshes.new(n); vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]; me.from_pydata(vs,[],[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]); me.materials.append(m); o=bpy.data.objects.new(n,me); bpy.context.collection.objects.link(o); o.location=loc; o.scale=dim; return o
for x in (-24,8,40):
 # Pitched roofs are visual landmarks in the supplied photograph.
 for s in (-1,1):
  ob=box('Gabled mill roof',(x,17+s*6.5,19.7),(30,14,.5),roof); ob.rotation_euler.x=s*math.radians(12)
 box('Illuminated clerestory windows',(x,4.45,13.5),(26,.1,.65),light)
# Dusk sky and restrained work lights.
w=bpy.context.scene.world; w.use_nodes=True; w.node_tree.nodes['Background'].inputs['Color'].default_value=(.045,.09,.18,1); w.node_tree.nodes['Background'].inputs['Strength'].default_value=.45
sun=bpy.data.objects.get('Overcast daylight')
if sun: sun.data.energy=.6; sun.data.color=(.55,.68,1)
for x,y,z in [(-50,-5,28),(-50,-5,44),(24,12,28),(24,12,44),(-5,-2,13),(33,0,13)]:
 data=bpy.data.lights.new('Furnace work light','POINT'); data.energy=800; data.color=(1,.78,.53); data.shadow_soft_size=3; o=bpy.data.objects.new('Furnace work light',data); bpy.context.collection.objects.link(o); o.location=(x,y,z)
cam=bpy.context.scene.camera; cam.animation_data_clear(); cam.data.lens=33
for f,loc,target in [(1,(40,-185,37),(-10,20,19)),(100,(15,-140,34),(-12,18,20)),(180,(-5,-70,27),(-18,8,16)),(260,(1,-12,16),(-1.4,-.4,3.8)),(360,(5,-10,5.7),(-1.5,-.4,3.8))]:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
for fc in cam.animation_data.action.fcurves:
 for k in fc.keyframe_points:k.interpolation='LINEAR'
sc=bpy.context.scene; sc.cycles.samples=6; sc.cycles.use_denoising=True; sc.frame_set(1); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/steelworks_dusk_preview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_furnaces_dusk.blend'); bpy.ops.render.render(write_still=True)
