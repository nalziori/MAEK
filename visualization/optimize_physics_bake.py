from pathlib import Path
p=Path('D:/obsd/Projects/hackerton/MAEK/visualization/build_furnace_physics_blender.py')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'));sc=bpy.context.scene", "bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'));sc=bpy.context.scene\nfor ob in sc.objects:\n if ob.type=='CAMERA' and ob.animation_data:ob.animation_data_clear()\nprint('PHYSICS_SOURCE_LOADED',flush=True)")
a=s.index('def box(name,p,d,m):');b=s.index('\ndef half(',a)
s=s[:a]+'''box_cache={}
def box(name,p,d,m):
 if m.name not in box_cache:
  me=bpy.data.meshes.new('Physics cube '+m.name)
  vs=[(x*.5,y*.5,z*.5) for x,y,z in [(-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),(1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)]]
  fs=[(0,2,6,4),(1,5,7,3),(0,4,5,1),(2,3,7,6),(0,1,3,2),(4,6,7,5)]
  me.from_pydata(vs,[],fs);me.materials.append(m);box_cache[m.name]=me
 ob=bpy.data.objects.new(name,box_cache[m.name]);phys.objects.link(ob);ob.location=p;ob.scale=d;return ob
'''+s[b:]
p.write_text(s,encoding='utf-8')
