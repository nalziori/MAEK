import time, sys
sys.path.insert(0,'tests')
from maek import params, strategy
from test_strategy import _cfg
cfg = _cfg(True)
cfg = params.with_values(cfg, {"defects.internal_pitting.rate_per_km": params.get(cfg,"defects.internal_pitting.rate_per_km")*10, "strategy.pit_scan_budget_frac":0.5})
for km,runs in ((10,12),):
    t=time.time()
    print(strategy.pit_prior_sensitivity(cfg, 1, runs, km, shares=(0.0,0.9)).round(3).to_string())
    print(time.time()-t)
