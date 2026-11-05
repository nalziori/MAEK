import sys
import numpy as np
from maek import params, ut, pit, evaluate as ev
cfg = params.load_config()
cfg = ev._with(cfg, "ut.pit.cfar_k_margin", 0.0)
pit._TAIL_FRAC = float(sys.argv[1]) if len(sys.argv) > 1 else 1/8
sig, lab = pit.make_dr_dataset(ev._with(cfg, "ut.pit.dr_pit_prob", 0.0), 1500, 0)
res = {}
for i in range(len(sig)):
    a = pit.analyse(cfg, sig[i], lab.wall_mm[i], lab.temp_meas_c[i])
    k = pit.cfar_k(cfg, pit._corr_cells(cfg, a["n_win"]))
    res.setdefault(lab.n_avg[i], []).append(a["stat"].max() - k if len(a["stat"]) else -9)
for na, v in sorted(res.items()):
    v = np.array(v)
    print(na, len(v), " ".join(f"m{m}:{(v > m).mean():.3f}" for m in (0, 0.25, 0.5, 0.75, 1.0, 1.25)))
allv = np.concatenate([np.array(v) for v in res.values()])
print("all", " ".join(f"m{m}:{(allv > m).mean():.3f}" for m in (0, 0.25, 0.5, 0.75, 1.0, 1.25)))
