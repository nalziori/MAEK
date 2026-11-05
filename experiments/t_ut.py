import sys
sys.path.insert(0, "/home/user/maek")
import numpy as np
from maek import params, ut
cfg = params.load_config()
st, an, lab = ut.make_dataset(cfg, 400, 0, "train")
th = np.array([ut.estimate_thickness(cfg, s, r.temp_c) for s, r in zip(st, lab.itertuples())])
err = np.abs(th - lab.wall_mm)
bad = lab[err > 0.5].copy(); bad["est"] = th[err > 0.5]
print(len(bad), "bad of", len(lab), "; pitted among bad:", int((bad.pit_depth_mm > 0).sum()), "; pitted total:", int((lab.pit_depth_mm>0).sum()))
print(bad[["wall_mm","pit_depth_mm","pit_fraction","est"]].head(10).to_string())
# pit fraction 0.5
for f in (0.3, 0.45, 0.5):
    s = ut.simulate_straight(cfg, np.random.default_rng(3), 8.0, pit_depth_mm=3.0, pit_fraction=f)
    print("frac", f, "est", ut.estimate_thickness(cfg, s), "min", ut.min_thickness(cfg, s))
