import sys
import numpy as np
from maek import params, ut, pit
cfg = params.load_config()
cond, na = sys.argv[1], int(sys.argv[2])
st, an, lab = ut.make_dataset(cfg, 600, 0, cond, n_avg=na)
temps = ut.analysis_temps(cfg, lab)
fs = 1e8
for i in np.nonzero(lab.pit_depth_mm.to_numpy() == 0)[0]:
    w = lab.wall_mm[i]
    a = pit.analyse(cfg, st[i], w, temps[i])
    r = pit.detect_rule(cfg, st[i], w, temps[i], a=a)
    if r["found"]:
        j = np.argmax(a["stat"])
        T_true = 2*w*1e-3/ut.velocity_long(cfg, lab.temp_c[i])
        print(f"wall {w:.2f} c {lab.coupling[i]:.2f} wmeas {a['wall_meas_mm']:.3f} tw_err {(a['tw']-1e-6-T_true)*fs:+.2f} smp  maxstat {a['stat'].max():.2f} at {(a['tw']-a['t'][j])*fs:.0f} smp before tw  sigma {a['sigma']:.4f} a_w {a['a_w']:.3f} nwin {a['n_win']} thr {pit.cfar_k(cfg, pit._corr_cells(cfg, a['n_win'])):.2f}")
