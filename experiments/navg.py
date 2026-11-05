import numpy as np
from maek import params, pit, evaluate as ev
cfg = params.load_config()
for N in (1, 4, 8, 16, 32, 64):
    c = ev._with(cfg, "ut.pit.dr_n_avg_choices", [N])
    sig, lab = pit.make_dr_dataset(c, 1200, 9)
    y = lab.pit_depth_mm.to_numpy() > 0
    f = np.array([pit.detect_rule(cfg, s, w, t)["found"] for s, w, t in zip(sig, lab.wall_mm, lab.temp_meas_c)])
    print(f"N={N:3d} DR det {f[y].mean():.3f} fa {f[~y].mean():.3f}", flush=True)
