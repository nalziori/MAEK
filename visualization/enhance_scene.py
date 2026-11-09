import bpy, math, random
from mathutils import Vector
random.seed(25)
bpy.ops.wm.open_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_pipe_environment.blend')
def material(n,col,metal=0,rough=.6):
 m=bpy.data.materials.new(n); m.diffuse_color=(*col,1); m.use_nodes=True; p=m.node_tree.nodes.get('Principled BSDF'); p.inputs['Base Color'].default_value=(*col,1); p.inputs['Metallic'].default_value=metal; p.inputs['Roughness'].default_value=rough; return m
def weather(m,a,b,scale,rough=.75):
 m.use_nodes=True; nt=m.node_tree; p=nt.nodes.get('Principled BSDF'); noise=nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=scale; noise.inputs['Detail'].default_value=5; noise.inputs['Roughness'].default_value=.8; ramp=nt.nodes.new('ShaderNodeValToRGB'); ramp.color_ramp.elements[0].position=.33; ramp.color_ramp.elements[0].color=(*a,1); ramp.color_ramp.elements[1].position=.68; ramp.color_ramp.elements[1].color=(*b,1); bump=nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.3; bump.inputs['Distance'].default_value=.07; nt.links.new(noise.outputs['Fac'],ramp.inputs[0]); nt.links.new(ramp.outputs[0],p.inputs['Base Color']); nt.links.new(noise.outputs['Fac'],bump.inputs['Height']); nt.links.new(bump.outputs[0],p.inputs['Normal']); p.inputs['Roughness'].default_value=rough
silver=bpy.data.materials['Insulation cladding']; steel=bpy.data.materials['Steel structure']; pipe=bpy.data.materials['Painted steel']; rust=bpy.data.materials['Surface corrosion']; yellow=bpy.data.materials['Safety yellow']; weather(silver,(.17,.19,.18),(.55,.57,.54),24,.5); weather(pipe,(.09,.11,.095),(.27,.22,.14),14); weather(rust,(.07,.025,.012),(.44,.15,.038),10,.9)
insulation=material('Exposed insulation fibres',(.51,.42,.23),0,.97); black=material('Instrument casing',(.035,.047,.052),.15,.65); blue=material('Instrument screen',(.025,.20,.25),.1,.35); orange=material('Inspection safety orange',(.75,.23,.025),.2,.5)
def cube(n,loc,dim,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc); o=bpy.context.object; o.name=n; o.dimensions=dim; bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); o.data.materials.append(m); return o
def cyl(n,a,b,r,m):
 d=Vector(b)-Vector(a); bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=r,depth=d.length,location=(Vector(a)+Vector(b))/2); o=bpy.context.object; o.name=n; o.rotation_euler=d.to_track_quat('Z','Y').to_euler(); o.data.materials.append(m); bpy.ops.object.shade_smooth(); return o
def path(n,pts,r,m):
 cu=bpy.data.curves.new(n,'CURVE'); cu.dimensions='3D'; cu.resolution_u=16; cu.bevel_depth=r; cu.bevel_resolution=4; sp=cu.splines.new('POLY'); sp.points.add(len(pts)-1)
 for p,co in zip(sp.points,pts): p.co=(*co,1)
 obj=bpy.data.objects.new(n,cu); bpy.context.collection.objects.link(obj); obj.data.materials.append(m); return obj
# Replace solid insulated line with separated cladding and a visible inspection window.
old=bpy.data.objects.get('Insulated steam'); bpy.data.objects.remove(old,do_unlink=True)
cyl('Steam jacket left',(-9,-.4,3.8),(-2.4,-.4,3.8),.40,silver); cyl('Steam jacket right',(-.65,-.4,3.8),(8.1,-.4,3.8),.40,silver)
cyl('Insulation exposed left',(-2.4,-.4,3.8),(-2.20,-.4,3.8),.37,insulation); cyl('Insulation exposed right',(-.85,-.4,3.8),(-.65,-.4,3.8),.37,insulation); cyl('Exposed corroded pipe',(-2.2,-.4,3.8),(-.85,-.4,3.8),.29,rust)
for i in range(14):
 x=random.uniform(-2.15,-.9); a=random.uniform(0,math.tau); y=-.4+math.cos(a)*.3; z=3.8+math.sin(a)*.3; bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=1,location=(x,y,z)); o=bpy.context.object; o.name='Illustrative corrosion pit'; o.scale=(random.uniform(.035,.09),.025,.035); o.data.materials.append(rust)
# 90-degree bends into descending vertical legs.
for y,z,r,m in [(-.4,3.8,.4,silver),(.65,4,.3,pipe),(1.5,3.9,.26,silver)]:
 pts=[]; R=.85
 for j in range(25):
  t=math.pi*.5*j/24; pts.append((8.1+R*math.sin(t),y,z-R*(1-math.cos(t))))
 pts.append((8.95,y,.65)); path('90 degree elbow and vertical pipe',pts,r,m)
# Additional flange rings at accessible bends.
for x in (6.8,7.4): cyl('Flange',(x-.06,.65,4),(x+.06,.65,4),.36,steel)
# Portable UT unit, probe and cable on an inspection stand.
cube('Inspection cart tabletop',(-1.5,-2.0,1.1),(1.15,.66,.09),steel)
for x in (-1.95,-1.05):
 for y in (-2.2,-1.8): cyl('Cart leg',(x,y,.08),(x,y,1.07),.035,steel)
cube('UT instrument',(-1.5,-2,1.29),(.55,.34,.30),orange); cube('UT display',(-1.5,-2.176,1.32),(.36,.015,.16),blue)
for x in (-1.68,-1.55,-1.42,-1.29): cube('UT control',(x,-2.179,1.22),(.055,.02,.025),black)
cyl('UT probe',(-1.22,-.76,3.85),(-1.22,-.69,3.85),.085,black); path('UT probe cable',[(-1.3,-1.88,1.4),(-1.1,-1.8,1.8),(-1.0,-1.4,2.3),(-1.22,-1.0,3.3),(-1.22,-.76,3.85)],.018,black)
# PEC probe sits on intact insulation, not the exposed metal.
cube('PEC probe',(1.1,-.82,3.8),(.32,.14,.38),black); path('PEC cable',[(1.1,-.9,3.8),(1,-1.3,3.3),(.6,-1.7,2),(.3,-2,1.3)],.018,black); cube('PEC portable unit',(.3,-2,1.2),(.45,.3,.38),orange); cube('PEC display',(.3,-2.158,1.25),(.28,.015,.13),blue)
cam=bpy.context.scene.camera; cam.location=(10,-15,6.5); cam.rotation_euler=(Vector((0,0,3.05))-cam.location).to_track_quat('-Z','Y').to_euler(); cam.data.lens=35
sc=bpy.context.scene; sc.cycles.samples=16; sc.render.filepath='D:/obsd/Projects/hackerton/MAEK/visualization/pipe_scene_detail_preview.png'; bpy.ops.wm.save_as_mainfile(filepath='D:/obsd/Projects/hackerton/MAEK/visualization/maek_pipe_environment_detail.blend'); bpy.ops.render.render(write_still=True)
