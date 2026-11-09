"""Generate collision-checked virtual micro-drone camera routes along every pipe."""
import bpy,json,math,sys,random
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from routing_geometry import rounded
from repair_pipe_connections import basis,tree,within
import audit_asset_overlap as au
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'));sc=bpy.context.scene
network=json.loads((ROOT/'drone_verified_network.json').read_text());au.network=network;au.line_map={l['id']:l for l in network['lines']};au.devs=network['devices'];au.nodes=network['nodes']
vs=[];ts=[];owners=[];dg=bpy.context.evaluated_depsgraph_get()
for ob in sc.objects:
 if not au.visible(ob):continue
 ev=ob.evaluated_get(dg);me=ev.to_mesh();me.calc_loop_triangles();off=len(vs)
 vs.extend(ev.matrix_world@v.co for v in me.vertices)
 ts.extend(tuple(off+i for i in t.vertices) for t in me.loop_triangles);owners.extend([au.group(ob)]*len(me.loop_triangles));ev.to_mesh_clear()
world=BVHTree.FromPolygons(vs,ts,all_triangles=True);del vs,ts
# 0.12 m radius micro-drone; conservative clearance and full swept route sampling.
R=.12;STEP=.18;CLEAR=R+STEP/2+.015
shells=[]
for did in network['devices']:
 ob=bpy.data.objects[did];corners=[ob.matrix_world@Vector(c) for c in ob.bound_box]
 lo=Vector([min(p[k] for p in corners) for k in range(3)]);hi=Vector([max(p[k] for p in corners) for k in range(3)])
 shells.append((lo,hi,tree(ob)))
def free(p):
 if p.z<.3:return False
 d=world.find_nearest(p)[3]
 if d is None or d<CLEAR:return False
 for lo,hi,t in shells:
  if all(lo[k]<p[k]<hi[k] for k in range(3)) and within(t,p):return False
 return True
segment_cache={}
def travel(a,b):
 # A sample with .225 m clearance every <= .18 m proves >= .135 m swept clearance.
 v=b-a;n=max(1,math.ceil(v.length/STEP))
 return all(free(a+v*(i/n)) for i in range(n+1))
def see(p,target,allowed,r):
 v=target-p;hit=world.ray_cast(p,v.normalized(),v.length+.05)
 return hit[0] is not None and owners[hit[2]] in allowed and (hit[0]-target).length<r*2+.25
random.seed(731)
def detour(a,b):
 if travel(a,b):return [b]
 # Bidirectional RRT, limited to a local 8 m neighbourhood of the inspection leg.
 low=Vector([min(a[k],b[k])-5 for k in range(3)]);high=Vector([max(a[k],b[k])+5 for k in range(3)]);low.z=max(.35,low.z)
 aa=[a];ap=[-1];bb=[b];bp=[-1]
 def grow(nodes,parents,target):
  ix=min(range(len(nodes)),key=lambda j:(nodes[j]-target).length_squared);d=target-nodes[ix]
  q=target if d.length<=1.2 else nodes[ix]+d.normalized()*1.2
  if not free(q) or not travel(nodes[ix],q):return None
  nodes.append(q);parents.append(ix);return len(nodes)-1
 def chain(nodes,parents,i):
  out=[]
  while i!=-1:out.append(nodes[i]);i=parents[i]
  return list(reversed(out))
 for iteration in range(1800):
  target=bb[-1] if iteration%5==0 else Vector([random.uniform(low[k],high[k]) for k in range(3)])
  i=grow(aa,ap,target)
  if i is not None:
   j=grow(bb,bp,aa[i])
   if j is not None and (bb[j]-aa[i]).length<1.8 and travel(aa[i],bb[j]):
    result=chain(aa,ap,i)+list(reversed(chain(bb,bp,j)))
    # Smooth out unnecessary RRT corners while preserving swept clearance.
    out=[result[0]];k=0
    while k<len(result)-1:
     nxt=next(j for j in range(len(result)-1,k,-1) if travel(result[k],result[j]));out.append(result[nxt]);k=nxt
    return out[1:]
  aa,bb=bb,aa;ap,bp=bp,ap
  # Restore orientation when returning chains.
  if aa[0]!=a:
   aa,bb=bb,aa;ap,bp=bp,ap
 return None
routes=[];failed=[]
for number,l in enumerate(network['lines']):
 ps=[Vector(p) for p in rounded(l)];samples=[]
 for a,b in zip(ps,ps[1:]):
  n=max(1,math.ceil((b-a).length/2.0))
  for k in range(n):
   q=a+(b-a)*(k/n)
   if not samples or (q-samples[-1][0]).length>.8:samples.append((q,(b-a).normalized()))
 samples.append((ps[-1],(ps[-1]-ps[-2]).normalized()))
 poses=[];ok=True;allowed={l['id']};view_radius=l['radius_m']
 # Junction fittings can be owned by another incident pipe.
 for other in network['lines']:
  if {l['from'],l['to']}&{other['from'],other['to']}:allowed.add(other['id']);view_radius=max(view_radius,other['radius_m'])
 for end in ('from','to'):
  did=network['nodes'][l[end]]['device']
  if did:allowed.add(did.split('.STAVE')[0]+'.BF' if '.STAVE' in did else did)
 for target,tangent in samples:
  u,v=basis(tangent);candidates=[]
  for distance in (.65,1.15,2.0,3.2):
   for k in range(16):
    direction=math.cos(k*math.tau/16)*u+math.sin(k*math.tau/16)*v
    p=target+direction*(l['radius_m']+distance)
    if free(p) and see(p,target,allowed,view_radius):candidates.append(p)
  if not candidates:
   for distance in (.65,1.15,2.0,3.2):
    for axial in (-1,1):
     for k in range(16):
      direction=(math.cos(k*math.tau/16)*u+math.sin(k*math.tau/16)*v+tangent*axial).normalized()
      p=target+direction*(l['radius_m']+distance)
      if free(p) and see(p,target,allowed,view_radius):candidates.append(p)
  if not candidates:
   failed.append({'line':l['id'],'reason':'no safe visible camera pose','target':list(target)});ok=False;break
  candidates.sort(key=lambda p:(p-poses[-1][0]).length if poses else (p-(target+Vector((0,-1.2,1.2)))).length)
  path=None
  if not poses:path=[candidates[0]]
  else:
   for q in candidates:
    if travel(poses[-1][0],q):path=[q];break
   if path is None:
    for q in candidates[:4]:
     path=detour(poses[-1][0],q)
     if path:break
  if path is None:
   failed.append({'line':l['id'],'reason':'no safe flight leg','target':list(target)});ok=False;break
  for q in path:poses.append((q,target.copy()))
 if ok:
  routes.append({'id':l['id'],'from':l['from'],'to':l['to'],'radius':R,'samples':len(samples),'waypoints':[{'position':list(p),'target':list(t)} for p,t in poses]})
 if number%20==0:print('DRONE_ROUTE',number+1,'OK',len(routes),'FAILED',len(failed),flush=True)
report={'status':'PASS' if not failed and len(routes)==240 else 'FAIL','routes':len(routes),'pipe_count':240,'radius_m':R,'minimum_certified_clearance_m':CLEAR-STEP/2,'sample_spacing_max_m':STEP,'failed':failed}
(ROOT/'drone_flight_report.json').write_text(json.dumps(report,indent=2));(ROOT/'drone_routes_blender.json').write_text(json.dumps({'routes':routes},indent=2))
print('DRONE_FLIGHT_REPORT',json.dumps(report),flush=True)
if failed:raise RuntimeError('Unreachable inspection routes; review report')
coll=bpy.data.collections.new('11_Drone_inspection_cameras');sc.collection.children.link(coll)
for route in routes:
 ca=bpy.data.cameras.new('DRONE '+route['id']);ca.lens=24;ca.clip_start=.04;ca.clip_end=2000
 cam=bpy.data.objects.new('DRONE '+route['id'],ca);coll.objects.link(cam);f=1
 for i,wp in enumerate(route['waypoints']):
  p=Vector(wp['position']);target=Vector(wp['target'])
  if i:f+=max(1,round((p-Vector(route['waypoints'][i-1]['position'])).length/2*24))
  cam.location=p;cam.rotation_euler=(target-p).to_track_quat('-Z','Y').to_euler();cam.keyframe_insert(data_path='location',frame=f);cam.keyframe_insert(data_path='rotation_euler',frame=f)
 cam['pipe_id']=route['id'];cam['flight_end_frame']=f;cam['drone_radius_m']=R
 if cam.animation_data and cam.animation_data.action:
  for fc in cam.animation_data.action.fcurves:
   for k in fc.keyframe_points:k.interpolation='LINEAR'
 sc.frame_end=max(sc.frame_end,f)
sc.camera=bpy.data.objects['DRONE BF1-WS001'];sc.frame_set(1)
sc['drone_inspection']='240 separately launched virtual camera routes; select DRONE camera by pipe ID; 0.12 m collision envelope, not aerodynamic simulation'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'))
# Unity coordinates Y-up.
unity=[]
for route in routes:
 row={k:v for k,v in route.items() if k!='waypoints'};row['waypoints']=[]
 for wp in route['waypoints']:
  row['waypoints'].append({k:[v[0],v[2],v[1]] for k,v in wp.items()})
 unity.append(row)
OUT=ROOT.parent/'unity/MAEKInspection/Assets/MAEK/Source'
(OUT/'drone_routes.json').write_text(json.dumps({'routes':unity},indent=2))
print('DRONE_CAMERAS_SAVED',len(routes),flush=True)

