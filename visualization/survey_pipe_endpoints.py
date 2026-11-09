import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from routing_geometry import rounded
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_interior_ready.blend'))
data=json.loads((ROOT/'interior_network.json').read_text())
dg=bpy.context.evaluated_depsgraph_get();trees={}
for eid in data['devices']:
 ob=bpy.data.objects.get(eid)
 if ob is None:continue
 ev=ob.evaluated_get(dg);me=ev.to_mesh();me.calc_loop_triangles()
 trees[eid]=BVHTree.FromPolygons([ev.matrix_world@v.co for v in me.vertices],[tuple(t.vertices) for t in me.loop_triangles],all_triangles=True)
 ev.to_mesh_clear()
rows=[];errors=[]
for l in data['lines']:
 ob=bpy.data.objects.get(l['id']);ps=rounded(l)
 for end,i,j,key in [('from',0,1,'from'),('to',-1,-2,'to')]:
  node=data['nodes'][l[key]];eid=node['device'];p=Vector(ps[i]);axis=(Vector(ps[j])-p).normalized();r=l['radius_m']
  actual=ob.matrix_world@Vector(ob.data.splines[0].points[i].co[:3]);err=(actual-p).length
  row={'line':l['id'],'end':end,'node':l[key],'device':eid,'position':list(p),'axis':list(axis),'radius':r,'centerline_error':err}
  if eid:
   tree=trees.get(eid)
   if tree is None:row['status']='MISSING_DEVICE'
   else:
    u=axis.cross(Vector((0,0,1)))
    if u.length<.1:u=axis.cross(Vector((0,1,0)))
    u.normalize();v=axis.cross(u).normalized();gaps=[];miss=0
    for k in range(17):
     q=p if k==16 else p+r*(math.cos(k*math.tau/16)*u+math.sin(k*math.tau/16)*v)
     hit=tree.ray_cast(q+axis*30,-axis,60)[0]
     if hit is None:miss+=1
     else:gaps.append((q-hit).dot(axis))
    row.update(max_gap_m=max(gaps) if gaps else None,min_gap_m=min(gaps) if gaps else None,missed_rays=miss,nearest_shell_m=tree.find_nearest(p)[3])
    row['status']='GAP' if miss or (gaps and max(gaps)>.003) else 'PASS'
  else:row['status']='PIPE_JOINT'
  rows.append(row)
report={'ends':len(rows),'device_ends':sum(bool(r['device']) for r in rows),'problems':[r for r in rows if r['status'] in ('GAP','MISSING_DEVICE')],'rows':rows}
(ROOT/'drone_endpoint_before.json').write_text(json.dumps(report,indent=2))
print('ENDPOINT_SURVEY',json.dumps({k:v for k,v in report.items() if k!='rows'}),flush=True)
