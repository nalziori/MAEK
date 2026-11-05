import time, sys
import numpy as np
from maek import params, ut, evaluate as ev
cfg = params.load_config()
d = "ut.dataset."
def factor(cfg, name):
    c = cfg
    keep = {"noise": ["shifted_noise_scale"], "coupling": ["shifted_coupling_range"],
            "temp_range": ["shifted_temp_range_c"], "temp_error": ["shifted_temp_meas_error_c"],
            "temp": ["shifted_temp_range_c", "shifted_temp_meas_error_c"]}[name]
    rev = {"shifted_noise_scale": 1.0, "shifted_coupling_range": params.get(cfg, d+"train_coupling_range"),
           "shifted_temp_range_c": params.get(cfg, d+"train_temp_range_c"),
           "shifted_temp_meas_error_c": params.get(cfg, d+"train_temp_meas_error_c")}
    for k, v in rev.items():
        if k not in keep:
            c = ev._with(c, d+k, v)
    return c
n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
for name, c, cond in [("train", cfg, "train"), ("noise", factor(cfg,"noise"), "shifted"),
                      ("coupling", factor(cfg,"coupling"), "shifted"), ("temp_range", factor(cfg,"temp_range"), "shifted"),
                      ("temp_error", factor(cfg,"temp_error"), "shifted"), ("temp", factor(cfg,"temp"), "shifted"),
                      ("shifted", cfg, "shifted")]:
    t = time.time()
    st, an, lab = ut.make_dataset(c, n, 0, cond)
    temps = ut.analysis_temps(c, lab)
    tm = np.array([ut.min_thickness(c, s, tt) for s, tt in zip(st, temps)])
    pit = lab.pit_depth_mm.to_numpy() > 0
    hit = np.nan_to_num(tm, nan=1e9) <= lab.wall_mm.to_numpy() - 0.3
    print(f"{name:10s} det {hit[pit].mean():.3f} fa {hit[~pit].mean():.3f}  ({time.time()-t:.1f}s)", flush=True)
