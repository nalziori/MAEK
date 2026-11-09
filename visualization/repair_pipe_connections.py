"""Actual mesh endpoint verification, nozzle repair and reusable audit; metres."""
import bpy,bmesh,json,sys,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from collections import defaultdict
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from routing_geometry import rounded
import audit_asset_overlap as clash

def tree(ob,cap=False):
 ev=ob.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh()
 bm=bmesh.new();bm.from_mesh(me)
 if cap:bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=0)
 bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();me.calc_loop_triangles()
 vs=[ev.matrix_world@v.co for v in me.vertices]
 t=BVHTree.FromPolygons(vs,[tuple(p.vertices) for p in me.loop_triangles],all_triangles=True)
 ev.to_mesh_clear();return t

def within(t,p,tol=.003):
 near=t.find_nearest(p)
 return near[0] is not None and (near[3]<=tol or clash.inside(t,p))

def basis(axis):
 u=axis.cross(Vector((0,0,1)))
 if u.length<.1:u=axis.cross(Vector((0,1,0)))
 u.normalize();return u,axis.cross(u).normalized()

def ring_vertices(ob,p,axis,r):
 ev=ob.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();out=[]
 for v in me.vertices:
  q=ev.matrix_world@v.co;d=q-p
  if abs(d.dot(axis))<.001 and abs(d.length-r)<.002:out.append(q.copy())
 ev.to_mesh_clear()
 if len(out)<8:raise RuntimeError('No evaluated end ring '+ob.name+' '+str(len(out)))
 return out

def audit_ends(data,nozzles={},joints={}):
 devtrees={k:tree(bpy.data.objects[k]) for k in data['devices']}
 pipes={l['id']:tree(bpy.data.objects[l['id']],True) for l in data['lines']}
 attachments={k:tree(o) for k,o in nozzles.items()};junctions={k:tree(o) for k,o in joints.items()}
 linked=defaultdict(list)
 for l in data['lines']:
  for key in ('from','to'):linked[l[key]].append(l['id'])
 rows=[]
 for l in data['lines']:
  ob=bpy.data.objects[l['id']];ps=rounded(l)
  for end,i,j in [('from',0,1),('to',-1,-2)]:
   nid=l[end];node=data['nodes'][nid];p=Vector(ps[i]);axis=(Vector(ps[j])-p).normalized();did=node['device']
   actual=ob.matrix_world@Vector(ob.data.splines[0].points[i].co[:3]);targets=[]
   if did:targets.append(devtrees[did])
   targets += [pipes[k] for k in linked[nid] if k!=l['id']]
   if nid in attachments:targets.append(attachments[nid])
   if nid in junctions:targets.append(junctions[nid])
   ring=ring_vertices(ob,p,axis,l['radius_m']);uncovered=[q for q in ring if not any(within(t,q) for t in targets)]
   row={'line':l['id'],'end':end,'node':nid,'device':did,'ring_samples':len(ring),'uncovered_ring_vertices':len(uncovered),'center_error_m':(actual-p).length,'pass':not uncovered and (actual-p).length<.0001}
   if uncovered:row['uncovered_positions']=[list(p) for p in uncovered]
   rows.append(row)
 return {'status':'PASS' if all(r['pass'] for r in rows) else 'FAIL','pipe_count':len(data['lines']),'endpoint_count':len(rows),'failed_endpoints':sum(not r['pass'] for r in rows),'scope':'Evaluated mesh endpoint rings against designated equipment, capped pipe volume proxies and verified fittings; not a fluid simulation','checks':rows}

def run():
 bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_interior_ready.blend'));sc=bpy.context.scene
 data=json.loads((ROOT/'interior_network.json').read_text())
 before=audit_ends(data);(ROOT/'mesh_endpoints_before.json').write_text(json.dumps(before,indent=2))
 print('BEFORE',before['failed_endpoints'],flush=True)
 coll=bpy.data.collections.new('10_Verified_pipe_connections');sc.collection.children.link(coll)
 nozzles={};joints={};repairs=[]
 for ob in list(sc.objects):
  if ob.type!='CURVE' or ob.name in {l['id'] for l in data['lines']} or not clash.visible(ob):continue
  for sp in list(ob.data.splines):
   if sp.type!='POLY' or len(sp.points)<8 or sp.use_cyclic_u:continue
   coords=[tuple(p.co) for p in sp.points]
   if (Vector(coords[0][:3])-Vector(coords[-1][:3])).length>.0001:continue
   ob.data.splines.remove(sp);new=ob.data.splines.new('POLY');new.points.add(len(coords)-2)
   for q,p in zip(new.points,coords[:-1]):q.co=p
   new.use_cyclic_u=True
 for l in data['lines']:
  if l['id'] in ('BF1-F003','BF2-F003'):
   nid=l['to'];did=data['nodes'][nid]['device'];a=Vector(l['points'][-2]);b=Vector(l['points'][-1]);hit=tree(bpy.data.objects[did]).ray_cast(a,(b-a).normalized(),(b-a).length)[0]
   if hit is None:raise RuntimeError('Missing stack interface')
   l['points'][-1]=list(hit);data['nodes'][nid]['position']=list(hit)
   ob=bpy.data.objects[l['id']];ob.data.splines[0].points[-1].co=(*hit,1)
   repairs.append({'line':l['id'],'action':'move buried stack node to measured exterior inlet face'})
  if l['id'] in ('BF1-G005','BF2-G005'):
   a=l['points'][0];b=l['points'][-1]
   l['points']=[a,[a[0],a[1],24],[b[0],b[1],24],b]
   ob=bpy.data.objects[l['id']];ob.data.splines.clear();sp=ob.data.splines.new('POLY');ps=rounded(l);sp.points.add(len(ps)-1)
   for p,v in zip(sp.points,ps):p.co=(*v,1)
   repairs.append({'line':l['id'],'action':'vertical scrubber outlet followed by elbow; was horizontal across top cap'})
 bpy.context.view_layer.update()
 interim=audit_ends(data);bad={r['node'] for r in interim['checks'] if not r['pass']}
 # Fit each equipment nozzle to its actual faceted shell, including slanted interfaces.
 for l in data['lines']:
  ps=rounded(l);ob=bpy.data.objects[l['id']]
  for end,i,j in [('from',0,1),('to',-1,-2)]:
   nid=l[end];did=data['nodes'][nid]['device']
   if not did or nid not in bad:continue
   shell=tree(bpy.data.objects[did]);p=Vector(ps[i]);axis=(Vector(ps[j])-p).normalized();u,v=basis(axis);r=l['radius_m'];outer=r+max(.008,r*.025);inner=r*.965
   length=min(.16,r*.8,(Vector(ps[j])-p).length*.5);N=64;vs=[];back=[]
   for radial,front in [(outer,False),(outer,True),(inner,True),(inner,False)]:
    for k in range(N):
     q=p+radial*(math.cos(k*math.tau/N)*u+math.sin(k*math.tau/N)*v)
     if front:q+=axis*length
     else:
      hit=shell.ray_cast(q+axis*30,-axis,60)[0]
      if hit is None:raise RuntimeError('Nozzle misses shell '+nid)
      q=hit-axis*.02
      if radial==outer:back.append(q.copy())
     vs.append(tuple(q))
   fs=[]
   for band in range(4):
    for k in range(N):fs.append((band*N+k,band*N+(k+1)%N,((band+1)%4)*N+(k+1)%N,((band+1)%4)*N+k))
   me=bpy.data.meshes.new(nid+' fitted nozzle');me.from_pydata(vs,[],fs);me.materials.append(ob.data.materials[0])
   for f in me.polygons:f.use_smooth=True
   nozzle=bpy.data.objects.new(l['id']+' shell-fit nozzle',me);coll.objects.link(nozzle);nozzle['line_id']=l['id'];nozzle['joint_node']=nid;nozzle['attached_equipment']=did
   nozzles[nid]=nozzle
   if not all(within(shell,q) for q in back):raise RuntimeError('Nozzle bond failed '+nid)
   repairs.append({'line':l['id'],'node':nid,'action':'shell-conforming welded nozzle','shell_samples':N,'shell_bond_pass':True})
 # Compact cast junction fittings close exposed mitre seams at angled segment joins.
 link=defaultdict(list)
 for l in data['lines']:
  for end in ('from','to'):link[l[end]].append(l)
 for nid in sorted(bad):
  if data['nodes'][nid]['device']:continue
  ls=link[nid];r=max(l['radius_m'] for l in ls)*1.015
  bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=24,radius=r,location=data['nodes'][nid]['position'])
  o=bpy.context.object;o.name=ls[0]['id']+' welded junction '+nid
  for c in list(o.users_collection):c.objects.unlink(o)
  coll.objects.link(o);o.data.materials.append(bpy.data.objects[max(ls,key=lambda l:l['radius_m'])['id']].data.materials[0]);o['line_id']=ls[0]['id'];o['joint_node']=nid
  for f in o.data.polygons:f.use_smooth=True
  joints[nid]=o;repairs.append({'node':nid,'action':'compact cast junction fitting','lines':[l['id'] for l in ls]})
 bpy.context.view_layer.update()
 final=audit_ends(data,nozzles,joints);final['repairs']=repairs
 (ROOT/'mesh_endpoints_after.json').write_text(json.dumps(final,indent=2))
 print('AFTER',final['failed_endpoints'],'NOZZLES',len(nozzles),'JUNCTIONS',len(joints),flush=True)
 assert final['status']=='PASS'
 (ROOT/'drone_verified_network.json').write_text(json.dumps(data,indent=2));sc['network_file']='drone_verified_network.json'
 from validate_connected_network import validate
 result=validate(data,write_report=False);(ROOT/'drone_connectivity_report.json').write_text(json.dumps(result,indent=2));assert result['status']=='PASS'
 result=clash.audit('drone_overlap_report.json')
 sc['endpoint_mesh_report']='mesh_endpoints_after.json';sc['verified_pipe_lines']=240
 bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'))
 print('REPAIR_SAVED','CLASHES',result['unreviewed_overlap_pairs'],flush=True)
 if result['unreviewed_overlap_pairs']:raise RuntimeError('Review new attachment clashes')
 from export_unity_geometry import export_scene
 export_scene(data)
 bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'))
if __name__=='__main__':run()
