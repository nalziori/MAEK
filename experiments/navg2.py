import time
import numpy as np
from maek import params, pit, evaluate as ev
cfg = params.load_config()
for N in (1, 4, 16, 64):
    c = ev._with(cfg, "ut.pit.dr_n_avg_choices", [N])
    sig, lab = pit.make_dr_dataset(c, 1500, 9)
    y = lab.pit_depth_mm.to_numpy() > 0
    out = {}
    t = time.time()
    for s, w, tt in zip(sig, lab.wall_mm, lab.temp_meas_c):
        a = pit.analyse(cfg, s, w, tt)
        for m in ("mf_cfar", "learned"):
            out.setdefault(m, []).append(pit.detect_pit(cfg, s, w, tt, m, a=a, n_avg=N)["found"])
    print(f"N={N:3d} " + " ".join(f"{m}: {np.mean(np.array(f)[y]):.3f}/{np.mean(np.array(f)[~y]):.3f}" for m, f in out.items()), flush=True)
st = sig[:200]; lb = lab.iloc[:200]
t = time.perf_counter()
for s, w, tt in zip(st, lb.wall_mm, lb.temp_meas_c):
    pit.detect_pit(cfg, s, w, tt, "learned", n_avg=64)
print("learned ms/A-scan", (time.perf_counter() - t) / 200 * 1e3)
t = time.perf_counter()
for s, w, tt in zip(st, lb.wall_mm, lb.temp_meas_c):
    pit.detect_pit(cfg, s, w, tt, "mf_cfar")
print("mf_cfar ms/A-scan", (time.perf_counter() - t) / 200 * 1e3)
