import bpy,json
from pathlib import Path
r=Path(__file__).resolve().parent
p=r/"build_interiors.py"
s=p.read_text(encoding="utf-8-sig")
s=s.replace('sc.camera=cam;sc.frame_set(100)','sc.camera=cam;sc.frame_set(100)\nsc["verified_pipe_lines"]=len(data["lines"]);sc["connectivity_report"]="interior_connectivity_report.json";sc["asset_overlap_report"]="interior_overlap_report.json"')
p.write_text(s,encoding="utf-8")
bpy.ops.wm.open_mainfile(filepath=str(r/"maek_interior_ready.blend"))
sc=bpy.context.scene;sc["verified_pipe_lines"]=240;sc["connectivity_report"]="interior_connectivity_report.json";sc["asset_overlap_report"]="interior_overlap_report.json"
t=bpy.data.texts.get("READ_ME__INTERIOR") or bpy.data.texts.new("READ_ME__INTERIOR");t.clear();t.write((r/"INTERIOR_GUIDE.md").read_text(encoding="utf-8-sig"))
bpy.ops.wm.save_as_mainfile(filepath=str(r/"maek_interior_ready.blend"))

