import bpy,json,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
from repair_pipe_connections import audit_ends,tree,within
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'));sc=bpy.context.scene
network=json.loads((ROOT/'drone_verified_network.json').read_text())
nozzles={o['joint_node']:o for o in sc.objects if o.get('attached_equipment')}
joints={o['joint_node']:o for o in sc.objects if o.get('joint_node') and not o.get('attached_equipment')}
r=audit_ends(network,nozzles,joints);bonds=[]
for nid,o in nozzles.items():
 shell=tree(bpy.data.objects[o['attached_equipment']]);ok=all(within(shell,o.matrix_world@v.co) for v in list(o.data.vertices)[:64]);bonds.append({'node':nid,'pass':ok})
assert r['status']=='PASS' and all(b['pass'] for b in bonds)
cams=[o for o in sc.objects if o.type=='CAMERA' and o.name.startswith('DRONE ')]
assert len(cams)==240
r['nozzle_shell_bonds']=bonds;r['saved_camera_routes']=len(cams);r['saved_blend']='maek_drone_verified.blend'
(ROOT/'saved_drone_model_verification.json').write_text(json.dumps(r,indent=2))
sc['connectivity_report']='drone_connectivity_report.json';sc['asset_overlap_report']='drone_overlap_report.json';sc['endpoint_mesh_report']='saved_drone_model_verification.json';sc['drone_flight_report']='drone_flight_report.json'
text=bpy.data.texts.get('READ_ME__DRONE') or bpy.data.texts.new('READ_ME__DRONE');text.clear();text.write((ROOT/'DRONE_INSPECTION_GUIDE.md').read_text(encoding='utf-8-sig'))
sc.camera=bpy.data.objects['DRONE BF1-WS011'];sc.frame_set(sc.camera['flight_end_frame'])
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'maek_drone_verified.blend'))
print('SAVED_MODEL_VERIFIED',r['endpoint_count'],'ENDS',len(bonds),'NOZZLE_BONDS',len(cams),'CAMERAS',flush=True)
