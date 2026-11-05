import numpy as np
from maek import params, ut, pit, evaluate as ev
cfg = params.load_config()
cfg0 = ev._with(cfg, "ut.pit.cfar_k_margin", 0.0)
sig, lab = pit.make_dr_dataset(ev._with(cfg, "ut.pit.dr_pit_prob", 0.0), 1500, 0)
fs = 1e8
for i in range(len(sig)):
    w = lab.wall_mm[i]
    a = pit.analyse(cfg, sig[i], w, lab.temp_meas_c[i])
    if not len(a["stat"]): continue
    k = pit.cfar_k(cfg0, pit._corr_cells(cfg, a["n_win"]))
    if a["stat"].max() - k > 0.75:
        j = np.argmax(a["stat"])
        v = ut.velocity_long(cfg, lab.temp_c[i]); T = 2*w*1e-3/v
        print(f"i{i} w {w:.2f} na {lab.n_avg[i]} c {lab.coupling[i]:.2f} ns {lab.noise_scale[i]:.2f} wmeas {a['wall_meas_mm']:.3f} tw_err {(a['tw']-1e-6-T)*fs:+.2f} stat {a['stat'].max():.2f} k {k:.2f} pos {(a['tw']-a['t'][j])*fs:.0f}smp before tw (nwin {a['n_win']}) sigma {a['sigma']:.4f} a_w {a['a_w']:.3f} T {T*fs:.0f}")
