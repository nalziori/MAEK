import sys
sys.path.insert(0, "/home/user/maek")
import numpy as np
from maek import params, network
from maek.camera import composite2d as c, jobs
cfg = params.load_config()
seg, feat, dfx = network.generate_network(cfg, 1, total_km=20)
js = jobs.make_jobs(cfg, seg, dfx, 120, 1)
bad = tot = 0
for i, j in enumerate(js):
    if not j["defects"]:
        continue
    rgb, mask = c.render_job(cfg, j, np.random.default_rng([1, i]))
    for cls in (1, 2, 3):
        lab, n = c.label_components(mask == cls)
        for k in range(1, n + 1):
            comp = lab == k
            if comp.sum() < 12:
                continue
            tot += 1
            pts = np.array(c.trace_contour(comp))
            ys, xs = np.nonzero(comp)
            if pts[:,0].min() > xs.min() or pts[:,0].max() < xs.max() or pts[:,1].min() > ys.min() or pts[:,1].max() < ys.max():
                bad += 1
print("components", tot, "contours missing part of bbox", bad)
