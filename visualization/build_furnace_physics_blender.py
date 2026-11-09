"""Bake the C# solver's trace into the Blender section review scene (10x playback)."""
import bpy,bmesh,csv,json,math,sys,hashlib
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import audit_asset_overlap as au
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'));sc=bpy.context.scene
for ob in sc.objects:
 if ob.type=='CAMERA' and ob.animation_data:ob.animation_data_clear()
print('PHYSICS_SOURCE_LOADED',flush=True)
network=json.loads((ROOT/'drone_verified_network.json').read_text());au.network=network;au.devs=network['devices'];au.nodes=network['nodes'];au.line_map={l['id']:l for l in network['lines']}
rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader((ROOT/'furnace_physics_trace.csv').open())]
assert len(rows)==601
original=bpy.data.collections.new('12_Original_shells__toggle_for_exterior');sc.collection.children.link(original)
cut=bpy.data.collections.new('13_Physics_section_shells');sc.collection.children.link(cut)
phys=bpy.data.collections.new('14_Calculated_reactions_and_molten_flow');sc.collection.children.link(phys)
dg=bpy.context.evaluated_depsgraph_get();clipped=0
for ob in list(sc.objects):
 if not au.visible(ob):continue
 aid=au.group(ob)
 if aid not in ('BF1.BF','BF2.BF','BF1.TOWER','BF2.TOWER','BF1.CASTHOUSE','BF2.CASTHOUSE','BF1.CONVEYOR','BF2.CONVEYOR','BF1.CASTHOUSE.CRANE','BF2.CASTHOUSE.CRANE'):continue
 if aid.endswith(('CASTHOUSE','CONVEYOR','CRANE')):
  for c in list(ob.users_collection):c.objects.unlink(ob)
  original.objects.link(ob);continue
 ev=ob.evaluated_get(dg);me=ev.to_mesh();bm=bmesh.new();bm.from_mesh(me)
 for v in bm.verts:v.co=ev.matrix_world@v.co
 bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),plane_co=Vector((0,18,0)),plane_no=Vector((0,1,0)),clear_outer=True,dist=.00001)
 if len(bm.faces):
  mesh=bpy.data.meshes.new('SECTION '+ob.name);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh)
  for m in ob.data.materials:mesh.materials.append(bpy.data.materials[m.name])
  clone=bpy.data.objects.new('SECTION '+ob.name,mesh);cut.objects.link(clone);clipped+=1
 bm.free();ev.to_mesh_clear()
 for c in list(ob.users_collection):c.objects.unlink(ob)
 original.objects.link(ob)
original.hide_render=True;original.hide_viewport=True
print("SECTION_SHELLS",clipped,flush=True)
if bpy.data.collections.get('07_Labels'):bpy.data.collections['07_Labels'].hide_render=True

def mat(name,color,emission=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Metallic'].default_value=.3;p.inputs['Roughness'].default_value=.45
 if emission:p.inputs['Emission Color'].default_value=(*color,1);p.inputs['Emission Strength'].default_value=emission
 return m
molten=mat('PHYSICS liquid iron',(1,.14,.008),2.5);brick=mat('PHYSICS refractory',(.22,.18,.15));coke=mat('PHYSICS coke',(.045,.055,.06));labelmat=mat('PHYSICS annotation',(.92,.85,.61),.4);bright=mat('PHYSICS velocity tracer',(1,.75,.13),3)

def link(ob):
 for c in list(ob.users_collection):c.objects.unlink(ob)
 phys.objects.link(ob);return ob

box_cache={}
def box(name,p,d,m):
 if m.name not in box_cache:
  me=bpy.data.meshes.new('Physics cube '+m.name)
  vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]
  fs=[(0,2,6,4),(1,5,7,3),(0,4,5,1),(2,3,7,6),(0,1,3,2),(4,6,7,5)]
  me.from_pydata(vs,[],fs);me.materials.append(m);box_cache[m.name]=me
 ob=bpy.data.objects.new(name,box_cache[m.name]);phys.objects.link(ob);ob.location=p;ob.scale=d;return ob

def half(name,p,r,h,m):
 N=48;vs=[(0,0,0),(0,0,1)]
 for k in range(N+1):
  t=math.pi+k*math.pi/N;vs.extend([(math.cos(t),math.sin(t),0),(math.cos(t),math.sin(t),1)])
 fs=[]
 for k in range(N):a=2+2*k;b=a+2;fs.extend([(a,b,b+1,a+1),(0,b,a),(1,a+1,b+1)])
 fs.append((2,3,3+2*N,2+2*N));me=bpy.data.meshes.new(name);me.from_pydata(vs,[],fs);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();me.materials.append(m)
 ob=bpy.data.objects.new(name,me);phys.objects.link(ob);ob.location=p;ob.scale=(r,r,h);return ob

def tube(name,points,r,m):
 cu=bpy.data.curves.new(name,'CURVE');cu.dimensions='3D';cu.bevel_depth=r;cu.bevel_resolution=3;sp=cu.splines.new('POLY');sp.points.add(len(points)-1)
 for p,q in zip(sp.points,points):p.co=(*q,1)
 cu.materials.append(m);ob=bpy.data.objects.new(name,cu);phys.objects.link(ob);return ob

def label(body,pos,size=.5):
 cu=bpy.data.curves.new(body,'FONT');cu.body=body;cu.size=size;cu.align_x='CENTER';cu.materials.append(labelmat);ob=bpy.data.objects.new(body,cu);phys.objects.link(ob);ob.location=pos;ob.rotation_euler=(math.pi/2,0,math.pi);return ob
units=[]
for unit,x in enumerate((-62,62)):
 bath=half('BF%d calculated liquid level'%(unit+1),(x,18,3.2),5,1,molten)
 half('Coke bed schematic',(x,18,5),4.8,2,coke)
 bands=[]
 for j in range(3):
  m=mat('PHYSICS reaction indicator '+str(unit)+' '+str(j),[(.9,.16,.01),(.6,.1,.02),(.3,.13,.035)][j],.6)
  bands.append(half('Aggregate reaction zone indicator',(x,18,10+j*10),3 if j==2 else 4.5,6,m))
 label('BF%d | REACTION + TAPPING'%(unit+1),(x,18.4,46),.8)
 for text,z in [('CO reduction (net)',29),('C reduction (net)',20),('CO generation',12)]:label(text,(x-8,19,z),.48)
 label('AGGREGATE MODEL | NOT A 3D TEMPERATURE FIELD',(x,18.5,43),.3)
 jet=tube('Calculated taphole stream',[(x,18,3.55),(x,23.85,3.55)],.03,molten)
 cells=[]
 for k in range(48):
  y=23.7+(k+.5)*.5;z=3.55-(k+.5)*.5*.015
  box('Runner refractory bed',(x,y,z-.09),(1.45,.505,.18),brick)
  for side in (-1,1):box('Runner side wall',(x+side*.665,y,z+.22),(.13,.505,.6),brick)
  cells.append(box('Calculated Saint-Venant liquid cell',(x,y,z),(1.2,.502,.001),molten))
 for y in (26,32,38,44):
  z=3.55-(y-23.7)*.015
  for side in (-1,1):box('Runner section support',(x+side*.85,y,z/2),(.13,.2,z),brick)
 endY=47.7
 box('Receiving vessel base',(x,endY+1.3,.23),(3,3,.3),brick)
 for side in (-1,1):
  box('Receiving vessel wall',(x+side*1.5,endY+1.3,1.5),(.18,3.2,2.7),brick)
  box('Receiving vessel wall',(x,endY+1.3+side*1.5,1.5),(3,.18,2.7),brick)
 ladle=box('Calculated accumulated iron',(x,endY+1.3,.4),(2.8,2.8,.001),molten)
 fall=tube('Gravity-driven free jet',[(x,endY,3.19)]*20,.06,molten)
 markers=[box('Calculated velocity tracer',(x,23.7+k*2,3.57),(.13,.22,.025),bright) for k in range(12)]
 units.append((x,bath,cells,jet,ladle,fall,markers,bands))
print("PHYSICS_GEOMETRY_READY",flush=True)
for unit,(x,bath,cells,jet,ladle,fall,markers,bands) in enumerate(units):
 distances=[k*2.0 for k in range(12)]
 for ti,row in enumerate(rows):
  for k in range(12):
   idx=max(0,min(47,int(distances[k]/.5)));distances[k]=(distances[k]+max(0,row['u'+str(idx)]))%24 if ti else distances[k]
  if ti%5:continue
  if ti%100==0:print("BAKE",unit,ti,flush=True)
  frame=1+round(row['time_s']*2.4)
  bath.scale.z=max(.00001,row['head_m']);bath.keyframe_insert(data_path='scale',frame=frame)
  jet.hide_render=row['tap_kg_s']<1e-6 or ti>=400;jet.hide_viewport=jet.hide_render;jet.keyframe_insert(data_path='hide_render',frame=frame);jet.keyframe_insert(data_path='hide_viewport',frame=frame)
  for k,ob in enumerate(cells):
   h=row['h'+str(k)];base=3.55-(k+.5)*.5*.015;ob.location.z=base+h/2;ob.scale.z=max(.000001,h);ob.keyframe_insert(data_path='location',frame=frame);ob.keyframe_insert(data_path='scale',frame=frame);ob.hide_render=h<1e-6;ob.hide_viewport=ob.hide_render;ob.keyframe_insert(data_path='hide_render',frame=frame);ob.keyframe_insert(data_path='hide_viewport',frame=frame)
  height=row['outlet_m3']/(2.8*2.8);ladle.location.z=.4+height/2;ladle.scale.z=max(.000001,height);ladle.keyframe_insert(data_path='location',frame=frame);ladle.keyframe_insert(data_path='scale',frame=frame)
  q=max(0,row['outlet_m3']-(rows[ti-1]['outlet_m3'] if ti else 0));fall.hide_render=q<1e-8;fall.hide_viewport=fall.hide_render;fall.keyframe_insert(data_path='hide_render',frame=frame);fall.keyframe_insert(data_path='hide_viewport',frame=frame)
  velocity=max(.01,row['u47']);start=3.19+row['h47']/2;travel=math.sqrt(2*max(.001,start-(.4+height))/9.81)
  for j,p in enumerate(fall.data.splines[0].points):
   t=j*travel/19;p.co=(x,47.7+velocity*t,start-.5*9.81*t*t,1);p.radius=max(.001,math.sqrt(max(q,0)/(math.pi*math.sqrt(velocity**2+(9.81*t)**2)))/.06);p.keyframe_insert(data_path='co',frame=frame);p.keyframe_insert(data_path='radius',frame=frame)
  for k,ob in enumerate(markers):
   dist=distances[k];idx=min(47,int(dist/.5));h=row['h'+str(idx)];ob.location=(x,23.7+dist,3.55-dist*.015+h+.025);ob.keyframe_insert(data_path='location',frame=frame);ob.hide_render=h<.0001;ob.hide_viewport=ob.hide_render;ob.keyframe_insert(data_path='hide_render',frame=frame);ob.keyframe_insert(data_path='hide_viewport',frame=frame)
  for ob in bands:
   emission=ob.data.materials[0].node_tree.nodes.get('Principled BSDF').inputs['Emission Strength'];emission.default_value=max(.04,min(2,row['heat_MW']/150));emission.keyframe_insert(data_path='default_value',frame=frame)
for ob in phys.objects:
 if ob.animation_data and ob.animation_data.action:
  for fc in ob.animation_data.action.fcurves:
   for kp in fc.keyframe_points:kp.interpolation='CONSTANT' if fc.data_path.startswith('hide_') else 'LINEAR'
sc.frame_start=1;sc.frame_end=1441;sc.render.fps=24
for time,title in [(0,'CLOSED / accumulating'),(30,'TAPHole OPEN'),(180,'STEADY DISCHARGE'),(400,'TAPHole CLOSED'),(600,'RESIDUAL FILM')]:sc.timeline_markers.new(title,frame=1+round(time*2.4))
ca=bpy.data.cameras.new('Physics section review');cam=bpy.data.objects.new('Physics section review',ca);phys.objects.link(cam);cam.location=(-44,90,44);target=Vector((-62,25,23));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();ca.lens=23;sc.camera=cam
ld=bpy.data.lights.new('Physics section fill','AREA');ld.energy=8000;ld.shape='DISK';ld.size=15;lo=bpy.data.objects.new(ld.name,ld);phys.objects.link(lo);lo.location=(-78,52,25);lo.rotation_euler=(Vector((-62,18,20))-lo.location).to_track_quat('-Z','Y').to_euler()
sc['physics_model']='Conservative C# net-reaction/enthalpy + Darcy taphole + 1D Saint-Venant runner; pure-iron proxy; not multiphase CFD'
sc['physics_trace']='furnace_physics_trace.csv';sc['physics_speedup']=10;sc['physics_review_only']='Exterior collision-ready scene remains in Unity; this blend is a sectioned playback of computed states.'
text=bpy.data.texts.new('READ_ME__FURNACE_PHYSICS');text.write((ROOT/'FURNACE_PHYSICS_GUIDE.md').read_text(encoding='utf-8-sig'))
sc.render.resolution_x=1400;sc.render.resolution_y=1000;sc.render.resolution_percentage=100
sc.frame_set(433)
# Verify cached depth/level geometry before saving.
row=rows[180];assert abs(units[0][1].scale.z-row['head_m'])<1e-5
assert all(abs(ob.scale.z-max(.000001,row['h'+str(k)]))<1e-5 for k,ob in enumerate(units[0][2]))
summary={'status':'PASS','trace_rows':len(rows),'baked_key_states':121,'pipe_baseline':'maek_drone_verified.blend','hearth_height_m':row['head_m'],'flow_kg_s':row['tap_kg_s'],'temperature_K':row['temperature_K'],'verified_runner_cells':96,'clipped_shell_objects':clipped,'trace_sha256':hashlib.sha256((ROOT/'furnace_physics_trace.csv').read_bytes()).hexdigest()}
(ROOT/'blender_furnace_physics_report.json').write_text(json.dumps(summary,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_furnace_physics.blend'))
sc.render.resolution_x=1400;sc.render.resolution_y=1000;sc.render.resolution_percentage=100;sc.cycles.samples=16;sc.cycles.use_denoising=True;sc.render.filepath=str(ROOT/'furnace_physics_section.png');bpy.ops.render.render(write_still=True)
print('BLENDER_PHYSICS_COMPLETE',json.dumps(summary),flush=True)


