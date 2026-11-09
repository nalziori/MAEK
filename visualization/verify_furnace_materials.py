import bpy,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_furnace_physics.blend'));sc=bpy.context.scene
count=0
for ob in bpy.data.collections['13_Physics_section_shells'].objects:
 original=bpy.data.objects.get(ob.name.removeprefix('SECTION '))
 if original and hasattr(original.data,'materials'):
  ob.data.materials.clear()
  for m in original.data.materials:
   if m:ob.data.materials.append(bpy.data.materials[m.name])
  assert len(ob.data.materials)>0,'Missing original material '+ob.name
  count+=1
sc.render.resolution_x=1400;sc.render.resolution_y=1000;sc.render.resolution_percentage=100
text=bpy.data.texts.get('READ_ME__FURNACE_PHYSICS');text.clear();text.write((ROOT/'FURNACE_PHYSICS_GUIDE.md').read_text(encoding='utf-8-sig'))
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_furnace_physics.blend'))
# Reopen to verify material pointers survive serialization, then render that saved file.
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_furnace_physics.blend'));sc=bpy.context.scene
assert all(len(o.data.materials)>0 and all(m is not None for m in o.data.materials) for o in bpy.data.collections['13_Physics_section_shells'].objects)
r=json.loads((ROOT/'blender_furnace_physics_report.json').read_text());r['saved_section_materials_verified']=count;(ROOT/'blender_furnace_physics_report.json').write_text(json.dumps(r,indent=2))
sc.cycles.samples=16;sc.render.filepath=str(ROOT/'furnace_physics_section.png');bpy.ops.render.render(write_still=True)
print('SAVED_SECTION_MATERIALS_VERIFIED',count,flush=True)
