"""Checks topology, explicit valve states and actual rounded pipe-centerline clearances."""
import json, math
from collections import defaultdict,deque
from pathlib import Path
from connected_network import export
from routing_geometry import rounded,closest
ROOT=Path(__file__).resolve().parent
def validate(data,write_report=True,verbose=True):
 nodes=data["nodes"];lines=data["lines"];deg=defaultdict(int);adj=defaultdict(list);errors=[]
 for l in lines:
  if l["from"] not in nodes or l["to"] not in nodes:errors.append("unknown endpoint "+l["id"]);continue
  for k,p in [(l["from"],l["points"][0]),(l["to"],l["points"][-1])]:
   deg[k]+=1
   if math.dist(p,nodes[k]["position"])>1e-5:errors.append("endpoint gap "+l["id"])
  if nodes[l["from"]]["medium"]!=nodes[l["to"]]["medium"]:errors.append("mixed service "+l["id"])
  if l["state"]=="open":adj[l["from"]].append(l["to"])
 for c in data["internal_connections"]:
  if c["active"]:adj[c["from"]].append(c["to"])
 for n,d in nodes.items():
  if deg[n]==0 and d["kind"]!="boundary":errors.append("unused port "+n)
  if d["kind"]=="boundary" and deg[n]==0 and not any(n in (c["from"],c["to"]) for c in data["internal_connections"]):errors.append("unattached boundary "+n)
  if d["kind"]=="junction" and deg[n]<2:errors.append("dangling junction "+n)
  if d["kind"]=="port" and deg[n]!=1:errors.append("port has incorrect pipe count "+n)
 def route(a,b):
  seen={a};q=deque([a])
  while q:
   n=q.popleft()
   if n==b:return True
   for nxt in adj[n]:
    if nxt not in seen:seen.add(nxt);q.append(nxt)
  return False
 checked=[]
 for r in data["required_routes"]:
  ok=route(r["from"],r["to"]);checked.append({**r,"pass":ok})
  if not ok:errors.append("no operating route: "+r["caption"])
 # Check isolation: ST1 fuel path must be blocked, ST2/3 blast delivery blocked.
 for prefix in ("BF1","BF2"):
  if route(prefix+".BF.G1",prefix+".ST1.GAS"):errors.append("ON_BLAST stove admits fuel")
  for stove in ("ST2","ST3"):
   if route(prefix+".CB.INTAKE",prefix+"."+stove+".COLD"):errors.append("ON_GAS stove admits cold blast")
 geoms=[]
 for l in lines:
  ps=rounded(l);r=l["radius_m"]
  lo=[min(p[i] for p in ps)-r for i in range(3)];hi=[max(p[i] for p in ps)+r for i in range(3)]
  segs=[(a,b,[min(a[i],b[i])-r for i in range(3)],[max(a[i],b[i])+r for i in range(3)]) for a,b in zip(ps,ps[1:])]
  geoms.append((l,lo,hi,segs))
 clashes=[]
 def overlap(lo,hi,l2,h2):return all(hi[k]>=l2[k] and h2[k]>=lo[k] for k in range(3))
 for i,(a,lo,hi,segs) in enumerate(geoms):
  for b,lo2,hi2,segs2 in geoms[i+1:]:
   if not overlap(lo,hi,lo2,hi2):continue
   shared=set([a["from"],a["to"]])&set([b["from"],b["to"]]);limit=a["radius_m"]+b["radius_m"]
   collision=None
   for p,q,sl,sh in segs:
    if collision:break
    for r,s,tl,th in segs2:
     if not overlap(sl,sh,tl,th):continue
     dist,cp,cq=closest(p,q,r,s)
     if dist>=limit-.003:continue
     if any(math.dist(cp,nodes[k]["position"])<limit*2.2 and math.dist(cq,nodes[k]["position"])<limit*2.2 for k in shared):continue
     collision={"a":a["id"],"b":b["id"],"clearance_m":round(dist-limit,4),"near":[round(x,3) for x in cp]};break
   if collision:clashes.append(collision)
 report={"status":"PASS" if not errors and not clashes else "FAIL","scope":"Pipe endpoints, graph reachability, explicit stove isolation, pairwise pipe centerline clearance with pipe radii. Not pressure/flow, wall thickness, structural clashes, support loads or engineering-code validation.","devices":len(data["devices"]),"lines":len(lines),"nodes":len(nodes),"required_flow_routes":len(checked),"topology_errors":errors,"pipe_clashes":clashes,"flow_checks":checked}
 if write_report:(ROOT/"connectivity_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
 if verbose:print(json.dumps({k:v for k,v in report.items() if k!="flow_checks"},ensure_ascii=False))
 return report
if __name__=="__main__":validate(export())

