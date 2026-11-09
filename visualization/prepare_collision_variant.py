from pathlib import Path
ROOT=Path(__file__).resolve().parent
s=(ROOT/"build_connected_steelworks.py").read_text(encoding="utf-8-sig")
s=s.replace("from connected_network import export","from collision_network import export")
s=s.replace('data=export(); report=validate(data)','data=export(); report=validate(data,write_report=False)\n(ROOT/"collision_connectivity_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")')
s=s.replace('me.from_pydata(vs,[],fs);me.materials.append(mat)','if kind=="box":fs=[tuple(reversed(f)) for f in fs]\n me.from_pydata(vs,[],fs);me.materials.append(mat)')
s=s.replace('def lathe(n,x,y,profile,m):','def lathe(n,x,y,profile,m,open_top=False):')
s=s.replace('fs.append(tuple(reversed(range(N))));fs.append(tuple((len(profile)-1)*N+i for i in range(N)))','fs.append(tuple(reversed(range(N))))\n if not open_top:fs.append(tuple((len(profile)-1)*N+i for i in range(N)))')
s=s.replace('rod(eid+" charging vessel",(x,y,46),(x,y,51),1.8,steel)','lathe(eid+" charging vessel",x,y,[(46,1.8),(50,1.8),(52.8,2.6)],steel,open_top=True)')
s=s.replace('(x+4,y,z),(x+9,y,z),1.3','(x-9,y,z),(x-4,y,z),1.3')
s=s.replace('(ox+px,-6,3.8),(.22,.4,7.0)','(ox+px,-6,3.855),(.22,.4,6.51)')
s=s.replace('(ox+px,-6,7.25),(.8,1.8,.12)','(ox+px,-6,7.18),(.8,1.8,.12)')
s=s.replace('box("stockhouse",(x,73,5),(16,13,10),silver)','box("stockhouse",(x,73,7.5),(16,13,15),silver)')
s=s.replace('a,b=Vector((x,68,10)),Vector((x,18,50))','a,b=Vector((x,68,16)),Vector((x,18,54))')
s=s.replace('rod("Inspection guardrail",(x-4.4,yy,5.65),(x+4.4,yy,5.65),.04,yellow)','if yy<-16:\n  rod("Inspection guardrail",(x-4.4,yy,5.65),(x-4.05,yy,5.65),.04,yellow)\n  rod("Inspection guardrail",(x-2.25,yy,5.65),(x+4.4,yy,5.65),.04,yellow)\n else:rod("Inspection guardrail",(x-4.4,yy,5.65),(x+4.4,yy,5.65),.04,yellow)')
s=s.replace('for dx in (-4,-2,0,2,4):rod("Inspection rail post"','for dx in (-4.1,-2,0,2,4):rod("Inspection rail post"')
anchor='# Weathered sleeve surface, not a hole/cut in the transport line.'
stairs='''# Stair access: 24 rises under the CharacterController step limit, with open landing.
for i in range(24):
 yy=-26.15+i*.4;top=(i+1)*4.64/24
 box("Inspection stair tread",(x-3.15,yy,top/2),(1.65,.4,top),steel)
for side in (-1,1):
 xx=x-3.15+side*.9
 rod("Inspection stair handrail",(xx,-26.35,1.05),(xx,-16.75,5.69),.035,yellow)
 for i in range(0,25,4):
  yy=-26.35+i*.4;bottom=i*4.64/24
  rod("Inspection stair rail post",(xx,yy,bottom),(xx,yy,bottom+1.05),.025,yellow)
'''
s=s.replace(anchor,stairs+anchor)
s=s.replace('maek_connected_steelworks.blend','maek_collision_ready.blend')
s=s.replace('connected_overview.png','collision_overview.png').replace('connected_furnace.png','collision_furnace.png').replace('connected_inspection.png','collision_inspection.png').replace('connected_flow_overview.png','collision_flow_overview.png')
s=s.replace('sc["verified_pipe_lines"]=len(data["lines"]);sc["connectivity_report"]="connectivity_report.json"','sc["verified_pipe_lines"]=len(data["lines"]);sc["connectivity_report"]="collision_connectivity_report.json";sc["network_file"]="collision_network.json"')
# Do not spend time rendering until the full geometry audit passes.
s=s[:s.index('for cam,name in [(hero,')]
s+='''\nfrom audit_asset_overlap import audit
result=audit("asset_overlap_after.json")
print("COLLISION_AUDIT_CANDIDATES",result["unreviewed_overlap_pairs"],flush=True)
if result["unreviewed_overlap_pairs"]:raise RuntimeError("Review asset_overlap_after.json before exporting.")
from export_unity_geometry import export_scene
export_scene(data)
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/"maek_collision_ready.blend"))
print("COLLISION_BUILD_COMPLETE",flush=True)
'''
s=s.replace('(52.8,2.6)', '(50.8,2.6)')
s=s.replace('box("open-center platform",(x,y+s*(w+hole)/4,z),(hole,thick,.18),steel)', 'if z==51 and s==1:\n   for sign in (-1,1):box("open-center platform",(x+sign*4.35,y+s*(w+hole)/4,z),(3.3,thick,.18),steel)\n  else:box("open-center platform",(x,y+s*(w+hole)/4,z),(hole,thick,.18),steel)')
s=s.replace('x-3.15','x-3.75').replace('(1.65,.4,top)','(1.3,.4,top)').replace('side*.9','side*.75')
s=s.replace('rod("Inspection guardrail",(x-4.4,yy,5.65),(x-4.05,yy,5.65),.04,yellow)\n  rod("Inspection guardrail",(x-2.25,yy,5.65),(x+4.4,yy,5.65),.04,yellow)', 'rod("Inspection guardrail",(x-3.0,yy,5.65),(x+4.4,yy,5.65),.04,yellow)')
s=s.replace('for dx in (-4.1,-2,0,2,4):rod("Inspection rail post",(x+dx,yy,4.6),(x+dx,yy,5.65),.025,yellow)', 'for dx in (-4.1,-2,0,2,4):\n  if yy<-16 and dx<-3:continue\n  rod("Inspection rail post",(x+dx,yy,4.6),(x+dx,yy,5.65),.025,yellow)')

(ROOT/"build_collision_ready.py").write_text(s,encoding="utf-8")
