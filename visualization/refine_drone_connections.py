from pathlib import Path
p=Path('D:/obsd/Projects/hackerton/MAEK/visualization/repair_pipe_connections.py')
s=p.read_text(encoding='utf-8-sig')
needle=" for l in data['lines']:\n  if l['id'] in ('BF1-G005','BF2-G005'):"
insert=""" for ob in list(sc.objects):
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
  if l['id'] in ('BF1-G005','BF2-G005'):"""
assert needle in s;s=s.replace(needle,insert);p.write_text(s,encoding='utf-8')
