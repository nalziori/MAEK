"""Public-PFD-based demonstration topology. Geometry and sizes are fictional, metres.
No POSCO as-built data, hydraulic solution, pressure rating, or complete P&ID.
"""
import math, json, csv
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCES=[
 {"id":"S1","url":"https://www.jstage.jst.go.jp/article/isijinternational/59/3/59_ISIJINT-2018-591/_html/-char/en","detail":"Figure 1, sections 1 and 2.1: dust catcher -> wet scrubber -> TRT; sedimentation and water recirculation. Linz BFA research, not POSCO."},
 {"id":"S2","url":"https://jnegroup.com/wp-content/uploads/2022/09/JNE-Automation_Blast-Furnace-Brochure_Download.pdf","detail":"Printed pp.12-15: cooling circuits, stove cycling, cold/hot blast, cleaned gas users. Public overview, not a detailed P&ID."},
 {"id":"S3","url":"https://www.primetals.com/en/portfolio/solutions/ironmaking/blast-furnace/gas-cleaning-plant/","detail":"Uptakes/downcomers, wet scrubber and integrated demisting, clean gas downstream."}]
nodes={}; lines=[]; devices={}; internal=[]; routes=[]
def make_module(prefix,offset):
 def P(p):return [round(p[0]+offset,6),round(p[1],6),round(p[2],6)]
 def key(s):return prefix+"."+s
 def dev(s,kind,center,dim,source="S2"):
  devices[key(s)]={"kind":kind,"center":P(center),"dimensions":dim,"source":source,"geometry_basis":"illustrative layout"}
  return key(s)
 def port(s,p,medium,device=None,kind="port"):
  q=key(s); assert q not in nodes
  nodes[q]={"position":P(p),"medium":medium,"device":key(device) if device else None,"kind":kind}
  return s
 def joint(s,p,medium):return port(s,p,medium,None,"junction")
 def edge(s,a,b,via=(),radius=.3,state="open",source="S2",raw=False):
  aid,bid=key(a),key(b)
  assert nodes[aid]["medium"]==nodes[bid]["medium"],(aid,bid)
  points=[list(nodes[aid]["position"])]+[P(p) for p in via]+[list(nodes[bid]["position"])]
  pts=[]
  for p in points:
   if not pts or math.dist(p,pts[-1])>1e-6:pts.append(p)
  line={"id":prefix+"-"+s,"from":aid,"to":bid,"medium":nodes[aid]["medium"],"radius_m":radius,"state":state,"source":source,"points":pts,"exact_polyline":raw,"dimensions_basis":"illustrative; not a design specification"}
  lines.append(line);return line
 def inside(a,b,active=True,kind="equipment passage"):
  internal.append({"from":key(a),"to":key(b),"active":active,"kind":kind})
 def trace(a,b,caption):routes.append({"from":key(a),"to":key(b),"caption":prefix+" "+caption})
 dev("BF","furnace",(0,18,0),[11,11,52])
 dev("DC","dust_catcher",(-18,34,0),[6.4,6.4,24],"S1")
 dev("SC","scrubber",(-33,34,0),[5,5,21],"S1")
 dev("TRT","turbine",(-44,34,4),[7,6,6],"S1")
 port("BF.G1",(-2,18,39),"BFG","BF");port("BF.G2",(2,18,39),"BFG","BF")
 joint("G.TOP",(0,14,49),"BFG")
 edge("G001","BF.G1","G.TOP",[(-2,14,46)],1.05,source="S3")
 edge("G002","BF.G2","G.TOP",[(2,14,46)],1.05,source="S3")
 port("DC.IN",(-18,34,24),"BFG","DC");port("DC.OUT",(-21.2,34,18),"BFG","DC")
 edge("G003","G.TOP","DC.IN",[(-14,14,49),(-18,34,29)],1.35,source="S3");inside("DC.IN","DC.OUT")
 port("SC.IN",(-30.5,34,10),"BFG","SC");port("SC.OUT",(-33,34,21),"BFG","SC")
 edge("G004","DC.OUT","SC.IN",[(-26,34,18),(-26,34,10)],1.0,source="S1");inside("SC.IN","SC.OUT")
 port("TRT.IN",(-44,34,7),"BFG","TRT");port("TRT.OUT",(-44,31,4),"BFG","TRT")
 edge("G005","SC.OUT","TRT.IN",[(-44,34,21)],.9,source="S1");inside("TRT.IN","TRT.OUT")
 joint("G.H0",(-12,-6,8),"BFG")
 edge("G006","TRT.OUT","G.H0",[(-44,-6,4),(-44,-6,8)],.75,source="S1")
 last="G.H0"
 for i,sx in enumerate((22,34,46)):
  joint("G.H"+str(i+1),(sx+4,-6,8),"BFG")
  edge("G10"+str(i),last,"G.H"+str(i+1),radius=.7);last="G.H"+str(i+1)
 dev("BO","boiler",(53,-26,5.5),[8,8,11])
 port("BO.G",(53,-22,6),"BFG","BO");edge("G110",last,"BO.G",[(56,-6,8),(56,-17,8),(53,-17,6)],.45)
 dev("BS","stack",(63,-26,0),[2,2,30]);port("BO.EX",(53,-26,11),"FLUE","BO");port("BS.IN",(63,-26,15),"FLUE","BS")
 port("BS.VENT",(63,-26,30),"FLUE","BS",kind="boundary")
 edge("F099","BO.EX","BS.IN",[(53,-26,15)],.7)
 inside("BO.G","BO.EX",kind="combustion / boiler black box");inside("BS.IN","BS.VENT")
 # Cold-blast and combustion-air blowers have explicitly declared atmosphere inlets.
 dev("CB","blower",(42,-18,3),[6,6,6])
 port("CB.INTAKE",(42,-21,3),"AIR","CB",kind="boundary");port("CB.OUT",(42,-15,4),"AIR","CB")
 inside("CB.INTAKE","CB.OUT")
 dev("CA","blower",(42,48,2),[6,6,4])
 port("CA.INTAKE",(42,51,2),"COMB_AIR","CA",kind="boundary");port("CA.OUT",(42,45,3),"COMB_AIR","CA");inside("CA.INTAKE","CA.OUT")
 dev("STK","stack",(56,37,0),[2.4,2.4,40]);port("STK.IN",(56,37,2),"FLUE","STK");port("STK.VENT",(56,37,40),"FLUE","STK",kind="boundary");inside("STK.IN","STK.VENT")
 for i,sx in enumerate((22,34,46)):
  n="ST"+str(i+1);active=(i==0)
  dev(n,"stove",(sx,25,0),[6,6,30]);devices[key(n)]["mode"]="ON_BLAST" if active else "ON_GAS"
  port(n+".COLD",(sx-1.0,22.172,4.5),"AIR",n)
  port(n+".HOT",(sx,22,10),"AIR",n)
  port(n+".GAS",(sx+3,25,6),"BFG",n)
  port(n+".AIR",(sx,28,5.5),"COMB_AIR",n)
  port(n+".FLUE",(sx-3,25,3),"FLUE",n)
  joint("C."+str(i),(sx,9,5),"AIR");joint("H."+str(i),(sx,12,12.4),"AIR")
  joint("A."+str(i),(sx,41,4),"COMB_AIR");joint("F."+str(i),(sx-4,37,2),"FLUE")
  edge("C20"+str(i),"C."+str(i),n+".COLD",[(sx-1,9,5),(sx-1,19,5)],.46,"open" if active else "closed")
  edge("H20"+str(i),n+".HOT","H."+str(i),[(sx,17,10),(sx,12,10)],.72,"open" if active else "closed")
  edge("G20"+str(i),"G.H"+str(i+1),n+".GAS",[(sx+4,18,8),(sx+4,25,8),(sx+4,25,6)],.4,"closed" if active else "open")
  edge("A20"+str(i),"A."+str(i),n+".AIR",[(sx,32,4),(sx,32,5.5)],.35,"closed" if active else "open")
  edge("F20"+str(i),n+".FLUE","F."+str(i),[(sx-4.5,25,3),(sx-4.5,37,3)],.6,"closed" if active else "open")
  inside(n+".COLD",n+".HOT",active,"regenerator ON_BLAST")
  inside(n+".GAS",n+".FLUE",not active,"combustion ON_GAS")
  inside(n+".AIR",n+".FLUE",not active,"combustion ON_GAS")
 edge("C001","CB.OUT","C.2",[(53,-15,4),(53,9,4),(53,9,5)],.65)
 edge("C002","C.2","C.1",radius=.65);edge("C003","C.1","C.0",radius=.65)
 edge("H001","H.2","H.1",radius=.85);edge("H002","H.1","H.0",radius=.85)
 edge("A001","CA.OUT","A.2",[(46,45,3),(46,41,3)],.5)
 edge("A002","A.2","A.1",radius=.5);edge("A003","A.1","A.0",radius=.5)
 edge("F001","F.0","F.1",radius=.65);edge("F002","F.1","F.2",radius=.65);edge("F003","F.2","STK.IN",radius=.65)
 # True ring headers: segmented at every tee; no uninterrupted pipe beneath branches.
 for k in range(12):
  t=math.radians(15+k*30)
  joint("B."+str(k),(6*math.cos(t),18+6*math.sin(t),12.4),"AIR")
  port("BF.T"+str(k),(5.5*math.cos(t),18+5.5*math.sin(t),10.7),"AIR","BF")
  edge("T"+str(k).zfill(3),"B."+str(k),"BF.T"+str(k),radius=.22)
  if k:pass
 for k in range(12):
  a=math.radians(15+k*30);b=a+math.pi/6
  mids=[(6*math.cos(a+(b-a)*j/10),18+6*math.sin(a+(b-a)*j/10),12.4) for j in range(1,10)]
  edge("B"+str(k).zfill(3),"B."+str(k),"B."+str((k+1)%12),mids,.55,raw=True)
 target=nodes[key("B.0")]["position"]; yy=target[1]
 edge("H003","H.0","B.0",[(12,12,12.4),(12,yy,12.4)],.85)
 # Stave cooling closed loop, isolated from process gas and hot blast.
 dev("HX","air_cooler",(-8,-24,2),[8,4,3])
 dev("CP","pump",(-23,-24,2),[4,3,3])
 port("HX.IN",(-4,-24,2),"CW","HX");port("HX.OUT",(-12,-24,2),"CW","HX");inside("HX.IN","HX.OUT")
 port("CP.IN",(-25,-24,2),"CW","CP");port("CP.OUT",(-21,-24,2),"CW","CP");inside("CP.IN","CP.OUT")
 edge("W001","HX.OUT","CP.IN",[(-14,-24,2),(-14,-29,2),(-27,-29,2),(-27,-24,2)],.23)
 for k in range(12):
  t=k*math.pi/6
  joint("WS."+str(k),(6.8*math.cos(t),18+6.8*math.sin(t),6.5),"CW")
  joint("WR."+str(k),(7.5*math.cos(t+.045),18+7.5*math.sin(t+.045),8.2),"CW")
  sn="STAVE"+str(k)
  dev(sn,"stave",(5.5*math.cos(t),18+5.5*math.sin(t),13),[.8,.8,7])
  port(sn+".IN",(5.55*math.cos(t-.045),18+5.55*math.sin(t-.045),9.8),"CW",sn)
  port(sn+".OUT",(5.55*math.cos(t+.045),18+5.55*math.sin(t+.045),16.2),"CW",sn)
  edge("WS"+str(k).zfill(3),"WS."+str(k),sn+".IN",[(6.8*math.cos(t),18+6.8*math.sin(t),9.8)],.12)
  edge("WR"+str(k).zfill(3),sn+".OUT","WR."+str(k),[(7.5*math.cos(t+.045),18+7.5*math.sin(t+.045),16.2)],.12)
  inside(sn+".IN",sn+".OUT")
 for tag,r,z,shift in [("WS",6.8,6.5,0),("WR",7.5,8.2,.045)]:
  for k in range(12):
   a=k*math.pi/6+shift;b=a+math.pi/6
   mid=[(r*math.cos(a+(b-a)*j/10),18+r*math.sin(a+(b-a)*j/10),z) for j in range(1,10)]
   edge(tag+"R"+str(k).zfill(3),tag+"."+str(k),tag+"."+str((k+1)%12),mid,.18,raw=True)
 edge("W002","CP.OUT","WS.9",[(-18,-24,2),(-18,-12,2),(-18,-12,6.5),(0,-12,6.5)],.23)
 wr=nodes[key("WR.9")]["position"];rx=wr[0]-offset
 edge("W003","WR.9","HX.IN",[(rx,7,8.2),(rx,7,10.5),(rx,-24,10.5),(rx,-24,2)],.23)
 # Wet cleaning water circuit: clarifier, recycle pump, make-up tank and sludge sink.
 dev("SET","clarifier",(-35,54,0),[12,12,3],"S1");dev("WP","pump",(-44,54,1.8),[4,3,2],"S1")
 dev("MW","makeup_tank",(-18,54,0),[6,6,6],"S1");dev("SL","sludge_receiver",(-35,65,1.5),[7,4,3],"S1")
 port("SC.W",(-35.5,34,14),"WASH","SC");port("SC.SL",(-33,34,1.5),"SLURRY","SC")
 port("SET.IN",(-33,48.343,2),"SLURRY","SET");port("SET.OUT",(-41,54,1.8),"WASH","SET")
 port("SET.MW",(-29,54,2),"WASH","SET");port("SET.SL",(-35,60,1),"SLURRY","SET")
 port("WP.IN",(-42,54,1.8),"WASH","WP");port("WP.OUT",(-44,52.5,1.8),"WASH","WP")
 port("MW.OUT",(-21,54,2),"WASH","MW",kind="boundary");port("SL.IN",(-35,63,1),"SLURRY","SL",kind="boundary")
 edge("Q001","SET.OUT","WP.IN",radius=.22,source="S1")
 edge("Q002","WP.OUT","SC.W",[(-44,45,1.8),(-38,45,1.8),(-38,34,1.8),(-38,34,14)],.22,source="S1")
 edge("Q003","SC.SL","SET.IN",[(-33,43,1.5),(-33,43,2)],.25,source="S1")
 edge("Q004","MW.OUT","SET.MW",radius=.18,source="S1")
 edge("Q005","SET.SL","SL.IN",radius=.22,source="S1")
 inside("WP.IN","WP.OUT");inside("SC.W","SC.SL",kind="wet scrubbing");inside("SET.IN","SET.OUT",kind="clarification");inside("SET.MW","SET.OUT");inside("SET.IN","SET.SL",kind="sludge separation")
 trace("BF.G1","BO.G","clean gas to boiler")
 trace("BF.G1","ST2.GAS","clean gas to firing stove")
 trace("CB.INTAKE","BF.T0","blower to tuyere through stove 1")
 trace("CP.OUT","HX.IN","cooling supply to return through staves")
 trace("SET.OUT","SET.IN","scrubber wash recirculation")
 trace("ST2.FLUE","STK.VENT","stove exhaust to stack")
 for k in range(12):
  trace("CP.OUT","STAVE"+str(k)+".IN","stave "+str(k)+" supply")
  trace("STAVE"+str(k)+".OUT","HX.IN","stave "+str(k)+" return")
make_module("BF1",-62)
make_module("BF2",62)
def export():
 data={"title":"MAEK connected process demonstration","units":"metres","basis":"Public PFD topology with fictional spatial arrangement. NOT POSCO P&ID.","sources":SOURCES,"devices":devices,"nodes":nodes,"lines":lines,"internal_connections":internal,"required_routes":routes}
 (ROOT/"connected_network.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
 with (ROOT/"connected_line_list.csv").open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.writer(f);w.writerow(["line_id","from","to","medium","diameter_m_ILLUSTRATIVE","state","source"])
  for l in lines:w.writerow([l["id"],l["from"],l["to"],l["medium"],l["radius_m"]*2,l["state"],l["source"]])
 return data
if __name__=="__main__":
 export()
 print(json.dumps({"devices":len(devices),"ports_and_junctions":len(nodes),"lines":len(lines)}))

