import time, pickle, os
import numpy as np
from maek import params, ut, pit
cfg = params.load_config()
cache = "/tmp/claude-0/-home-user/72a7cc9d-958e-56f6-8685-798eb6ea44d6/scratchpad/drfeat.pkl"
def feats(sig, lab):
    F, R = [], []
    for s, w, tt in zip(sig, lab.wall_mm, lab.temp_meas_c):
        a = pit.analyse(cfg, s, w, tt)
        F.append(pit.features(cfg, a, True)); R.append(pit.detect_rule(cfg, s, w, tt, a=a)["score"])
    return np.array(F), np.array(R)
if os.path.exists(cache):
    D = pickle.load(open(cache, "rb"))
else:
    D = {}
    for k, (n, sd) in {"tr": (4000, 1), "cal": (3000, 2), "val": (3000, 3)}.items():
        sig, lab = pit.make_dr_dataset(cfg, n, sd)
        F, R = feats(sig, lab)
        D[k] = (F, R, lab)
    pickle.dump(D, open(cache, "wb"))
Ftr, _, ltr = D["tr"]; ytr = ltr.pit_depth_mm.to_numpy() > 0
for hid, shadow in ((0, False), (16, False), (32, False), (16, True)):
    cols = slice(None) if shadow else slice(0, 7)
    m = pit.fit_mlp(Ftr[:, cols], ytr, hidden=hid)
    Fc, Rc, lc = D["cal"]; yc = lc.pit_depth_mm.to_numpy() > 0
    Fv, Rv, lv = D["val"]; yv = lv.pit_depth_mm.to_numpy() > 0
    pc = pit.predict_proba(m, Fc[:, cols]); pv = pit.predict_proba(m, Fv[:, cols])
    out = []
    for fa in (0.002, 0.005, 0.01):
        t = np.quantile(pc[~yc], 1 - fa); tr_ = np.quantile(Rc[~yc], 1 - fa)
        out.append(f"FA{fa}: L {(pv[yv]>t).mean():.3f}/{(pv[~yv]>t).mean():.3f} R {(Rv[yv]>tr_).mean():.3f}/{(Rv[~yv]>tr_).mean():.3f}")
    print(f"hid {hid} shadow {shadow}: " + " | ".join(out))
Fv, Rv, lv = D["val"]; yv = lv.pit_depth_mm.to_numpy() > 0
print("rule at design thr (score>1): det", (Rv[yv] > 1).mean(), "fa", (Rv[~yv] > 1).mean())
m = pit.fit_mlp(Ftr[:, :7], ytr, hidden=16)
Fc, Rc, lc = D["cal"]; yc = lc.pit_depth_mm.to_numpy() > 0
pc = pit.predict_proba(m, Fc[:, :7]); pv = pit.predict_proba(m, Fv[:, :7])
t = np.quantile(pc[~yc], 0.995)
bins = [-np.inf, 2.5, 3.0, 3.5, 4.0, np.inf]
bv = np.digitize(Fv[:, 3], bins)
for b in range(1, len(bins)):
    s = bv == b
    print(f"bw_snr bin {bins[b-1]}..{bins[b]}: n0 {(s & ~yv).sum()} FA L {(pv[s & ~yv] > t).mean():.3f} R {(Rv[s & ~yv] > 1).mean():.3f} | det L {(pv[s & yv] > t).mean():.3f} R {(Rv[s & yv] > 1).mean():.3f}")
print("bw_snr quantiles of val", np.quantile(Fv[:, 3], [0.1, 0.25, 0.5, 0.75, 0.9]))
