"""Regression cases for actual disconnection, cross-service joins, collision and valve isolation."""
from copy import deepcopy
from connected_network import export
from validate_connected_network import validate
def check(d):return validate(d,write_report=False,verbose=False)
original=export()
broken=deepcopy(original);broken["lines"][0]["points"][0][0]+=1
assert any("endpoint gap" in e for e in check(broken)["topology_errors"])
broken=deepcopy(original);broken["nodes"][broken["lines"][0]["from"]]["medium"]="CW"
assert any("mixed service" in e for e in check(broken)["topology_errors"])
broken=deepcopy(original)
sample=next(l for l in broken["lines"] if l["id"]=="BF1-G100")
copy=deepcopy(sample);copy["id"]="intentional_collision"
for endpoint in ("from","to"):
 old=copy[endpoint];new=old+".test";broken["nodes"][new]=deepcopy(broken["nodes"][old]);broken["nodes"][new]["kind"]="port";copy[endpoint]=new
broken["lines"].append(copy)
assert any("intentional_collision" in (c["a"],c["b"]) for c in check(broken)["pipe_clashes"])
broken=deepcopy(original)
next(l for l in broken["lines"] if l["id"]=="BF1-G200")["state"]="open"
assert any("admits fuel" in e for e in check(broken)["topology_errors"])
assert check(original)["status"]=="PASS"
print("PASS: disconnected endpoint, mixed service, physical collision and incorrect stove isolation detected; pristine model passes.")

