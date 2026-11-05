import pickle
import numpy as np
from maek import params, pit, evaluate as ev
cfg = params.load_config()
S = "/tmp/claude-0/-home-user/72a7cc9d-958e-56f6-8685-798eb6ea44d6/scratchpad/"
D = pickle.load(open(S + "drfeat.pkl", "rb"))
F0 = pickle.load(open(S + "cal0.pkl", "rb"))
_, l0 = pit.make_dr_dataset(ev._with(cfg, "ut.pit.dr_pit_prob", 0.0), 5000, 4)
n0 = l0.n_avg.to_numpy()
Ftr, _, ltr = D["tr"]; ytr = ltr.pit_depth_mm.to_numpy() > 0
Fv, Rv, lv = D["val"]; yv = lv.pit_depth_mm.to_numpy() > 0; nv = lv.n_avg.to_numpy()
m = pit.fit_mlp(Ftr[:, :7], ytr, hidden=16)
p0 = pit.predict_proba(m, F0[:, :7]); pv = pit.predict_proba(m, Fv[:, :7])
def report(name, hit):
    print(name, f"det {hit[yv].mean():.3f} fa {hit[~yv].mean():.3f} |", " ".join(f"n{na}: {hit[yv & (nv == na)].mean():.3f}/{hit[~yv & (nv == na)].mean():.3f}" for na in (1, 4, 16)))
for K in (1, 2, 4):
    hit = np.zeros(len(pv), bool)
    for na in (1, 4, 16):
        s0 = n0 == na; sv = nv == na
        edges = np.quantile(F0[s0, 3], np.linspace(0, 1, K + 1)[1:-1])
        b0 = np.digitize(F0[s0, 3], edges); bv = np.digitize(Fv[sv, 3], edges)
        thr = np.array([np.quantile(p0[s0][b0 == k], 0.995) for k in range(K)])
        hit[sv] = pv[sv] > thr[bv]
    report(f"learned n_avg x K{K}", hit)
edges = np.quantile(F0[:, 3], [0.25, 0.5, 0.75]); thr = np.array([np.quantile(p0[np.digitize(F0[:, 3], edges) == k], 0.995) for k in range(4)])
report("learned bw K4      ", pv > thr[np.digitize(Fv[:, 3], edges)])
report("rule (design)      ", Rv > 1)
for na in (1, 4, 16):
    pass
