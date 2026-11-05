import pickle
import numpy as np
from maek import pit
D = pickle.load(open("/tmp/claude-0/-home-user/72a7cc9d-958e-56f6-8685-798eb6ea44d6/scratchpad/drfeat.pkl", "rb"))
names = list(pit.FEATURES) + ["shadow"]
Ftr, _, ltr = D["tr"]; ytr = ltr.pit_depth_mm.to_numpy() > 0
Fc, Rc, lc = D["cal"]; yc = lc.pit_depth_mm.to_numpy() > 0
Fv, Rv, lv = D["val"]; yv = lv.pit_depth_mm.to_numpy() > 0
bins = [-np.inf, 2.5, 3.0, 3.5, np.inf]
bv = np.digitize(Fv[:, 3], bins)
for sub in (["snr_max"], ["snr_max", "snr_train"], ["snr_max", "snr_train", "excess"],
            ["snr_max", "snr_train", "excess", "depth_frac"],
            ["snr_max", "snr_train", "excess", "depth_frac", "rel_amp"],
            ["snr_max", "snr_train", "excess", "depth_frac", "train_ratio"],
            ["snr_max", "snr_train", "excess", "depth_frac", "rel_amp", "bw_snr"],
            list(pit.FEATURES)):
    cols = [names.index(s) for s in sub]
    m = pit.fit_mlp(Ftr[:, cols], ytr, hidden=16)
    pc = pit.predict_proba(m, Fc[:, cols]); pv = pit.predict_proba(m, Fv[:, cols])
    t = np.quantile(pc[~yc], 0.995)
    fa = [(pv[(bv == b) & ~yv] > t).mean() for b in range(1, len(bins))]
    dt = [(pv[(bv == b) & yv] > t).mean() for b in range(1, len(bins))]
    print(f"{'+'.join(sub):60s} det {(pv[yv] > t).mean():.3f} fa {(pv[~yv] > t).mean():.3f} | FA by bw_snr {np.round(fa, 3)} det {np.round(dt, 2)}")
t = 1
print(f"{'rule':60s} det {(Rv[yv] > t).mean():.3f} fa {(Rv[~yv] > t).mean():.3f} | FA by bw_snr {np.round([(Rv[(bv == b) & ~yv] > t).mean() for b in range(1, len(bins))], 3)} det {np.round([(Rv[(bv == b) & yv] > t).mean() for b in range(1, len(bins))], 2)}")
