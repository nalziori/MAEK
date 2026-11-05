import numpy as np
from maek import params, ut, pit, evaluate as ev
cfg = params.load_config()
narrow = cfg
for k, v in (("dr_noise_scale_range", [0.5, 2.0]), ("dr_coupling_range", [0.5, 1.0]),
             ("dr_temp_range_c", [-10, 80]), ("dr_temp_meas_error_max_c", 5.0)):
    narrow = ev._with(narrow, "ut.pit." + k, v)
models = {"std": pit.get_model(cfg), "narrow": pit.train_classifier(narrow)}
def run(sig, lab, tag):
    temps = lab["temp_meas_c"].to_numpy() if "condition" not in lab else ut.analysis_temps(cfg, lab)
    pm = lab.pit_depth_mm.to_numpy() > 0
    res = {}
    for s, w, t, na in zip(sig, lab.wall_mm, temps, lab.n_avg):
        a = pit.analyse(cfg, s, w, t)
        smax = a["stat"].max() if len(a["stat"]) else 0
        cells = pit._corr_cells(cfg, a["n_win"])
        for mn, mdl in models.items():
            f = pit.detect_learned(cfg, a, mdl, na)["found"]
            for g in (None, 0.0, 0.25, -0.25):
                ok = True if g is None else smax > pit.cfar_k(ev._with(cfg, "ut.pit.cfar_k_margin", g), cells)
                res.setdefault((mn, g), []).append(f and ok)
        res.setdefault(("rule", None), []).append(pit.detect_rule(cfg, s, w, t, a=a)["found"])
    for k, v in res.items():
        v = np.array(v)
        print(f"{tag} {k}: det {v[pm].mean():.3f} fa {v[~pm].mean():.3f}", flush=True)
for na in (1, 16):
    st, _, lab = ut.make_dataset(cfg, 2000, 0, "shifted", n_avg=na)
    run(st, lab, f"shifted n{na}")
    c = ev._with(cfg, "ut.pit.dr_n_avg_choices", [na])
    sig, lab = pit.make_dr_dataset(c, 2000, int(params.get(cfg, "ut.pit.dr_seed")) + 100)
    run(sig, lab.assign(n_avg=na), f"DRval n{na}")
