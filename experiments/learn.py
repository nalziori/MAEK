import time
import numpy as np
from maek import params, ut, pit
cfg = params.load_config()
import sys; HID = int(sys.argv[1])
t = time.time()
def feats(sig, lab, shadow):
    out = []
    for s, w, tt in zip(sig, lab.wall_mm, lab.temp_meas_c):
        a = pit.analyse(cfg, s, w, tt)
        out.append((pit.features(cfg, a, shadow), pit.detect_rule(cfg, s, w, tt, a=a)["found"]))
    return np.array([o[0] for o in out]), np.array([o[1] for o in out])
sig, lab = pit.make_dr_dataset(cfg, 4000, 1)
calib, clab = pit.make_dr_dataset(cfg, 2000, 2)
print("gen", time.time() - t)
sets = {}
for name, cond in (("train", "train"), ("shifted", "shifted")):
    for na in (1, 16):
        st, an, lb = ut.make_dataset(cfg, 1500, 0, cond, n_avg=na)
        lb = lb.copy(); lb["temp_meas_c"] = ut.analysis_temps(cfg, lb)
        sets[(name, na)] = (st, lb)
for shadow in (False, True):
    X, rule = feats(sig, lab, shadow); y = lab.pit_depth_mm.to_numpy() > 0
    Xc, rc = feats(calib, clab, shadow); yc = clab.pit_depth_mm.to_numpy() > 0
    m = pit.fit_mlp(X, y, hidden=HID)
    pc = pit.predict_proba(m, Xc)
    thr = np.quantile(pc[~yc], 1 - 0.005)
    print("shadow", shadow, "thr", thr, "calib det", (pc[yc] > thr).mean(), "rule calib det", rc[yc].mean(), "fa", rc[~yc].mean())
    for k, (st, lb) in sets.items():
        Xs, rs = feats(st, lb, shadow)
        ys = lb.pit_depth_mm.to_numpy() > 0
        ps = pit.predict_proba(m, Xs) > thr
        print(f"  {k}: learned det {ps[ys].mean():.3f} fa {ps[~ys].mean():.3f} | rule det {rs[ys].mean():.3f} fa {rs[~ys].mean():.3f}")
print("total", time.time() - t)
