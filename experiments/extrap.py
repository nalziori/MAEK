"""Learned classifier trained on DR ranges that do NOT cover shifted (extrapolation check)."""
import numpy as np
from maek import params, ut, pit, evaluate as ev
cfg = params.load_config()
narrow = cfg
for k, v in (("dr_noise_scale_range", [0.5, 2.0]), ("dr_coupling_range", [0.5, 1.0]),
             ("dr_temp_range_c", [-10, 80]), ("dr_temp_meas_error_max_c", 5.0)):
    narrow = ev._with(narrow, "ut.pit." + k, v)
models = {"learned": pit.train_classifier(narrow)}
for na in (1, 16):
    st, _, lab = ut.make_dataset(cfg, 3000, 0, "shifted", n_avg=na)
    h = ev.pit_detections(cfg, st, lab, ("learned", "mf_cfar"), models)
    pm = lab.pit_depth_mm.to_numpy() > 0
    for m, (f, _) in h.items():
        print(f"narrow-DR n_avg={na} {m}: shifted det {f[pm].mean():.3f} fa {f[~pm].mean():.3f}", flush=True)
