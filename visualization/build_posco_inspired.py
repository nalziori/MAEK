import bpy, math
from mathutils import Vector
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_steelworks_large.blend')
def mat(n,c,metal=0,rough=.6):
 m=bpy.data.materials.new(n); m.diffuse_color=(*c,1); m.use_nodes=True; p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*c,1); p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough; return m
def cube(n,loc,dim,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc); o=bpy.context.object; o.name=n; o.dimensions=dim; bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); o.data.materials.append(m); return o
def cyl(n,loc,r,depth,m):
 bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=r,depth=depth,location=loc); o=bpy.context.object; o.name=n; o.data.materials.append(m); return o
roof=mat('Pohang inspired blue green roof',(.16,.27,.29),.45); yellow=mat('Yellow gas main visual',(.56,.39,.07),.5); red=mat('Stack markings rust red',(.47,.12,.08),.4); white=mat('Stack markings pale',(.72,.71,.66),.25); sea=mat('Distant sea',(.13,.26,.31),.2,.5); asphalt=bpy.data.materials['Asphalt']; steel=bpy.data.materials['Steel structure']
for o in bpy.data.objects:
 if o.type=='MESH' and ('roof' in o.name.lower()) and o.data.materials: o.data.materials[0]=roof
# Coastal context is scenic, not surveyed geography.
cube('Distant coastal water',(0,205,-.79),(550,80,.12),sea)
# Distinctive striped stacks at varying heights.
for x,y,h in [(-78,82,44),(72,82,52),(123,82,43),(35,37,48)]:
 for j in range(8):
  z=(j+.5)*h/8; cyl('Striped stack', (x,y,z),1.05+(7-j)*.055,h/8+.02,red if j%2 else white)
# Multi-scale pipelines inspired by POSCO exterior photos.
for j in range(4):
 y=-22.7+j*.65; z=12.1+j*.35
 bpy.ops.mesh.primitive_cylinder_add(vertices=24,radius=.22,depth=280,location=(0,y,z),rotation=(0,math.pi/2,0)); o=bpy.context.object; o.name='Yellow overhead utility line'; o.data.materials.append(yellow)
# Additional interconnecting conveyors and enclosed overhead bridges.
for x in (-100,-62,2,56,108):
 cube('Elevated enclosed conveyor',(x,67,15),(4,52,3),roof)
 for y in (45,60,75,90): cube('Conveyor steel support',(x,y,7),(.35,.35,14),steel)
# Keep approach above the foreground rack, then descend behind it.
cam=bpy.context.scene.camera; cam.animation_data_clear(); cam.data.lens=32
for f,loc,target in [(1,(138,-195,96),(0,40,12)),(75,(90,-135,68),(0,35,11)),(150,(25,-62,30),(-1,5,5)),(210,(3,-32,21),(-1,0,4)),(255,(1,-12,16),(-1.4,-.4,3.8)),(360,(5,-10,5.7),(-1.5,-.4,3.8))]:
 cam.location=loc; cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler(); cam.keyframe_insert(data_path='location',frame=f); cam.keyframe_insert(data_path='rotation_euler',frame=f)
for fc in cam.animation_data.action.fcurves:
 for k in fc.keyframe_points: k.interpolation='LINEAR'
sc=bpy.context.scene; sc.frame_start=1; sc.frame_end=360; sc.render.fps=24; sc.cycles.samples=6; sc.cycles.use_denoising=True; sc.frame_set(1); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/posco_inspired_overview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_posco_inspired.blend'); bpy.ops.render.render(write_still=True)
sc.frame_set(300); sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/posco_inspired_approach.png'; bpy.ops.render.render(write_still=True)
