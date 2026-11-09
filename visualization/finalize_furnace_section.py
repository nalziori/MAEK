import bpy,json,sys,csv
from pathlib import Path
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import audit_asset_overlap as au
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_furnace_physics.blend'));sc=bpy.context.scene
archive=bpy.data.collections['12_Original_shells__toggle_for_exterior'];hidden=[]
for ob in list(sc.objects):
 if not au.visible(ob):continue
 aid=au.group(ob)
 if aid in ('BF1.CONVEYOR','BF2.CONVEYOR','BF1.CASTHOUSE.CRANE','BF2.CASTHOUSE.CRANE'):
  for c in list(ob.users_collection):c.objects.unlink(ob)
  archive.objects.link(ob);hidden.append(ob.name)
sc.camera.data.lens=23;sc.render.resolution_x=1400;sc.render.resolution_y=1000;sc.render.resolution_percentage=100
for mark in sc.timeline_markers:
 if mark.frame==1441:mark.name='RESIDUAL FILM'
rows=[{k:float(v) for k,v in r.items()} for r in csv.DictReader((ROOT/'furnace_physics_trace.csv').open())]
checks=[]
for seconds in (0,180,450,600):
 sc.frame_set(1+round(seconds*2.4))
 for x,prefix in ((-62,'BF1'),(62,'BF2')):
  bath=bpy.data.objects[prefix+' calculated liquid level'];assert abs(bath.scale.z-max(.00001,rows[seconds]['head_m']))<1e-5
  cells=sorted((o for o in sc.objects if o.name.startswith('Calculated Saint-Venant liquid cell') and abs(o.location.x-x)<.01),key=lambda o:o.location.y)
  assert len(cells)==48
  assert all(abs(o.scale.z-max(.000001,rows[seconds]['h'+str(k)]))<1e-5 for k,o in enumerate(cells))
  checks.append({'time_s':seconds,'furnace':prefix,'hearth_and_48_cells':'PASS'})
sc.frame_set(433);sc['section_occluders_hidden']='Conveyors and casting cranes hidden only in this derived section scene'
report=json.loads((ROOT/'blender_furnace_physics_report.json').read_text());report['saved_state_checks']=checks;report['view_occluders_hidden']=len(hidden)
(ROOT/'blender_furnace_physics_report.json').write_text(json.dumps(report,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_furnace_physics.blend'))
sc.cycles.samples=16;sc.render.filepath=str(ROOT/'furnace_physics_section.png');bpy.ops.render.render(write_still=True)
print('FINAL_SECTION_VERIFIED',len(checks),'STATES',len(hidden),'OCCLUDERS_HIDDEN',flush=True)
