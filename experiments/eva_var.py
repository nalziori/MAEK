import sys, time
sys.path.insert(0, "/home/user/maek-int")
from maek import eva, params
base = params.load_config()
def setv(cfg, key, v):
    import copy
    c = copy.deepcopy(cfg); node = c
    for p in key.split(".")[:-1]: node = node[p]
    node[key.split(".")[-1]]["value"] = v
    return c
variants = {
  "mid_sparse": setv(base, "eva.circuit_keys", ["medium", "area", "material", "decade"]),
  "mid_dense": setv(setv(base, "eva.circuit_keys", ["medium", "area", "material", "decade"]), "eva.pit_density_median_per_m2", 20.0),
}
for name, cfg in variants.items():
    t = time.time()
    df = eva.run(cfg, seed=0, runs=3, total_km=100, k_values=[4, 8])
    s = df.groupby("k")[["n_circuits","n_critical","sensitivity","false_alarm_rate","coverage","direct_detection","fallback_rate","scans","scanned_length_frac"]].mean()
    print(f"== {name} ({time.time()-t:.0f}s)"); print(s.round(3).to_string())
