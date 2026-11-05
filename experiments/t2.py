import time
from maek import params, strategy
cfg = params.load_config(None, [params.scenario_path("steam")])
t=time.time()
res = strategy.run_all(cfg, 1, 3, 5.0)
print(time.time()-t)
for n,df in res.items():
    print(n, df[["detection_rate_cui","pec_zones","pec_m","pec_hours","insulation_openings","scaffolds","trap_tests","energy_found_frac","ut_points","drone_ut_points","cost_krw"]].mean().round(3).to_dict())
lc = params.with_values(cfg, {"strategy.human_elevated_access":"lift"})
res = strategy.run_all(lc, 1, 3, 5.0)
for n,df in res.items():
    print(n, df[["scaffolds","lift_days","cost_krw","labor_hours"]].mean().round(3).to_dict())
