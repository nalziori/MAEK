"""Collision-corrected variant; preserves original public-PFD connectivity and IDs."""
import json,csv,copy,math
from pathlib import Path
import connected_network as base
ROOT=Path(__file__).resolve().parent
def export():
 d=copy.deepcopy({"title":"MAEK collision-ready connected steelworks","units":"metres","basis":"Public PFD; fictional layout, not POSCO P&ID","sources":base.SOURCES,"devices":base.devices,"nodes":base.nodes,"lines":base.lines,"internal_connections":base.internal,"required_routes":base.routes})
 for prefix,x in (("BF1",-62),("BF2",62)):
  for i,side in ((1,-1),(2,1)):
   d["nodes"][prefix+".BF.G"+str(i)]["position"]=[x+side*2,15.6040868,39]
  d["nodes"][prefix+".SC.SL"]["position"]=[x-33,35.72,1.5]
  for k in range(12):
   device=d["devices"][prefix+".STAVE"+str(k)];cx,cy,_=device["center"]
   angle=k*math.pi/6
   for kind,r,phi in (("IN",6.8,angle),("OUT",7.5,angle+.045)):
    node=d["nodes"][prefix+".STAVE"+str(k)+"."+kind];p=node["position"]
    goal=[x+r*math.cos(phi),18+r*math.sin(phi)]
    dx,dy=goal[0]-p[0],goal[1]-p[1];length=math.hypot(dx,dy);dx/=length;dy/=length
    tx=((cx+.4 if dx>0 else cx-.4)-p[0])/dx if abs(dx)>1e-9 else 1e9
    ty=((cy+.4 if dy>0 else cy-.4)-p[1])/dy if abs(dy)>1e-9 else 1e9
    leave_box=min(tx,ty)
    qx,qy=p[0]-x,p[1]-18;b=qx*dx+qy*dy
    leave_shell=-b+math.sqrt(max(0,b*b-(qx*qx+qy*qy-5.7*5.7)))
    distance=max(leave_box,leave_shell);node["position"]=[p[0]+dx*distance,p[1]+dy*distance,p[2]]
  for k in range(12):
   n=d["nodes"][prefix+".B."+str(k)];p=n["position"];p[0]=x+(p[0]-x)*8.6/6;p[1]=18+(p[1]-18)*8.6/6
  for l in d["lines"]:
   if not l["id"].startswith(prefix+"-"):continue
   tag=l["id"].split("-")[1]
   if tag.startswith("B") and tag[1:].isdigit():
    for p in l["points"]:p[0]=x+(p[0]-x)*8.6/6;p[1]=18+(p[1]-18)*8.6/6
   l["points"][0]=list(d["nodes"][l["from"]]["position"]);l["points"][-1]=list(d["nodes"][l["to"]]["position"])
   if tag=="G001":l["points"]=[list(d["nodes"][l["from"]]["position"]),[x-4,13.3,39],[x-4,13.3,46],list(d["nodes"][l["to"]]["position"])]
   if tag=="G002":l["points"]=[list(d["nodes"][l["from"]]["position"]),[x+4,13.3,39],[x+4,13.3,46],list(d["nodes"][l["to"]]["position"])]
   if tag=="C001":l["points"]=[list(d["nodes"][l["from"]]["position"]),[x+42,-12.5,4],[x+53,-12.5,4],[x+53,9,4],[x+53,9,5],list(d["nodes"][l["to"]]["position"])]
   if tag=="A001":l["points"]=[list(d["nodes"][l["from"]]["position"]),[x+42,43.5,3],[x+46,43.5,3],[x+46,41,3],list(d["nodes"][l["to"]]["position"])]
   if tag=="H003":l["points"][-2][1]=l["points"][-1][1]
   if tag=="W001":l["points"]=[list(d["nodes"][l["from"]]["position"]),[x-12.7,-24,2],[x-12.7,-32,2],[x-12.7,-32,3],[x-27,-32,3],[x-27,-24,3],[x-27,-24,2],list(d["nodes"][l["to"]]["position"])]
 (ROOT/"collision_network.json").write_text(json.dumps(d,indent=2),encoding="utf-8")
 with (ROOT/"collision_line_list.csv").open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.writer(f);w.writerow(["id","from","to","medium","radius_m_assumed","state","source"])
  for l in d["lines"]:w.writerow([l[k] for k in ("id","from","to","medium","radius_m","state","source")])
 return d
