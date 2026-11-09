import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from routing_geometry import rounded
from repair_pipe_connections import basis
network=json.loads((ROOT/'drone_verified_network.json').read_text())
for state,file in [('before','maek_interior_ready.blend'),('after','maek_drone_verified.blend')]:
 bpy.ops.wm.open_mainfile(filepath=str(ROOT/file));sc=bpy.context.scene
 for name,lid,end in [('stave','BF1-WS011','to'),('gas','BF1-G001','from')]:
  l=next(l for l in network['lines'] if l['id']==lid);ps=rounded(l);i,j=(0,1) if end=='from' else (-1,-2)
  p=Vector(ps[i]);axis=(Vector(ps[j])-p).normalized();u,v=basis(axis);scale=1 if name=='stave' else 3.2
  ca=bpy.data.cameras.new('Connection closeup');cam=bpy.data.objects.new('Connection closeup',ca);sc.collection.objects.link(cam)
  cam.location=p+axis*(1.4*scale)+u*(-1.0*scale)+Vector((0,0,.55*scale));cam.rotation_euler=(p-cam.location).to_track_quat('-Z','Y').to_euler();ca.lens=48;ca.clip_start=.02;sc.camera=cam
  ld=bpy.data.lights.new('Connection inspection light','AREA');ld.energy=110*scale*scale;ld.size=1.5*scale;lo=bpy.data.objects.new(ld.name,ld);sc.collection.objects.link(lo);lo.location=cam.location;lo.rotation_euler=cam.rotation_euler
  sc.render.engine='CYCLES';sc.cycles.samples=12;sc.cycles.use_denoising=True;sc.render.resolution_x=800;sc.render.resolution_y=600;sc.render.resolution_percentage=100;sc.render.filepath=str(ROOT/('connection_'+name+'_'+state+'.png'))
  bpy.ops.render.render(write_still=True);print('RENDERED',name,state,flush=True)
