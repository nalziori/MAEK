import time, sys
import numpy as np
from maek import params, ut, pit
cfg = params.load_config()
n = int(sys.argv[1]) if len(sys.argv) > 1 else 600
navgs = [int(a) for a in sys.argv[2].split(",")] if len(sys.argv) > 2 else [1, 16]
for cond in ("train", "shifted"):
    for na in navgs:
        st, an, lab = ut.make_dataset(cfg, n, 0, cond, n_avg=na)
        temps = ut.analysis_temps(cfg, lab)
        pitm = lab.pit_depth_mm.to_numpy() > 0
        wall = lab.wall_mm.to_numpy()
        tm = np.array([ut.min_thickness(cfg, s, t) for s, t in zip(st, temps)])
        hit = np.nan_to_num(tm, nan=1e9) <= wall - 0.3
        print(f"{cond:8s} n_avg={na:2d} baseline        det {hit[pitm].mean():.3f} fa {hit[~pitm].mean():.3f}")
        for mf, cf in ((True, False), (False, True), (True, True)):
            t = time.time()
            r = [pit.detect_rule(cfg, s, w, tt, mf, cf) for s, w, tt in zip(st, wall, temps)]
            f = np.array([x["found"] for x in r]); de = np.array([x["depth_est_mm"] for x in r])
            derr = np.abs(de - lab.pit_depth_mm.to_numpy())[pitm & f]
            print(f"{cond:8s} n_avg={na:2d} mf={mf:d} cfar={cf:d}  det {f[pitm].mean():.3f} fa {f[~pitm].mean():.3f}  depthMAE {np.median(derr) if len(derr) else np.nan:.3f}  ({(time.time()-t)/n*1e3:.1f} ms)", flush=True)
