import pickle, os
import numpy as np
from maek import params, pit, evaluate as ev
cfg = params.load_config()
S = "/tmp/claude-0/-home-user/72a7cc9d-958e-56f6-8685-798eb6ea44d6/scratchpad/"
D = pickle.load(open(S + "drfeat.pkl", "rb"))
if not os.path.exists(S + "cal0.pkl"):
    sig, lab = pit.make_dr_dataset(ev._with(cfg, "ut.pit.dr_pit_prob", 0.0), 5000, 4)
    F = np.array([pit.features(cfg, pit.analyse(cfg, s, w, t), True) for s, w, t in zip(sig, lab.wall_mm, lab.temp_meas_c)])
    pickle.dump(F, open(S + "cal0.pkl", "wb"))
F0 = pickle.load(open(S + "cal0.pkl", "rb"))
names = list(pit.FEATURES) + ["shadow"]
Ftr, _, ltr = D["tr"]; ytr = ltr.pit_depth_mm.to_numpy() > 0
Fv, Rv, lv = D["val"]; yv = lv.pit_depth_mm.to_numpy() > 0
bins = [-np.inf, 2.5, 3.0, 3.5, np.inf]
bv = np.digitize(Fv[:, 3], bins)
for K in (1, 4, 6, 8):
  for sub in (list(pit.FEATURES), list(pit.FEATURES) + ["shadow"]):
    cols = [names.index(s) for s in sub]
    m = pit.fit_mlp(Ftr[:, cols], ytr, hidden=16)
    p0 = pit.predict_proba(m, F0[:, cols]); pv = pit.predict_proba(m, Fv[:, cols])
    edges = np.quantile(F0[:, 3], np.linspace(0, 1, K + 1)[1:-1])
    s0 = np.digitize(F0[:, 3], edges); sv = np.digitize(Fv[:, 3], edges)
    thr = np.array([np.quantile(p0[s0 == k], 0.995) for k in range(K)])
    hit = pv > thr[sv]
    fa = [hit[(bv == b) & ~yv].mean() for b in range(1, len(bins))]
    dt = [hit[(bv == b) & yv].mean() for b in range(1, len(bins))]
    print(f"K{K} {'shadow' if len(sub) > 7 else 'base  '} det {hit[yv].mean():.3f} fa {hit[~yv].mean():.3f} | FA by bw_snr {np.round(fa, 3)} det {np.round(dt, 2)}")
