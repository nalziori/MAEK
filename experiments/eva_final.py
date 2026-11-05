import sys, time
sys.path.insert(0, "/home/user/maek-int")
from maek import eva, params
out = "/tmp/claude-0/-home-user/72a7cc9d-958e-56f6-8685-798eb6ea44d6/scratchpad/eva_final"
base = params.load_config()
for name, dens in (("sparse", 2.0), ("dense", 20.0)):
    cfg = params.with_values(base, {"eva.pit_density_median_per_m2": dens})
    t = time.time()
    df = eva.run(cfg, seed=1, runs=10, total_km=100)
    s = eva.summary(df)
    df.to_csv(f"{out}/eva_runs_{name}.csv", index=False)
    s.to_csv(f"{out}/eva_summary_{name}.csv", index=False)
    print(f"== {name} density {dens}/m2 ({time.time()-t:.0f}s)")
    print(eva.to_markdown(s))
