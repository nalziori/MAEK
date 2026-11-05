import copy
from maek import network, params
c=copy.deepcopy(params.load_config())
s,f,d=network.generate_network(c,seed=3,total_km=5)
g=d.groupby("kind").agg(n=("depth_mm","size"),dsum=("depth_mm","sum"),asum=("area_cm2","sum"))
print(g.round(3)); print(len(s),len(f))
