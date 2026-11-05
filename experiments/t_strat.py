import sys, time
sys.path.insert(0, "/home/user/maek")
import numpy as np
from maek import params, network, strategy
cfg = params.load_config()
seg, feat, dfx = network.generate_network(cfg, 0)
print("segments", len(seg), "features", len(feat), "defects", len(dfx))
t=time.perf_counter(); ids=set(dfx["segment_id"]); clean=[s for s in seg["segment_id"] if s not in set(dfx["segment_id"])]; print("comprehension rebuild set", time.perf_counter()-t)
t=time.perf_counter(); clean2=[s for s in seg["segment_id"] if s not in ids]; print("hoisted", time.perf_counter()-t)
t=time.perf_counter(); strategy.run_ai_triage(cfg, seg, feat, dfx, np.random.default_rng(0)); print("ai triage total", time.perf_counter()-t)
t=time.perf_counter(); strategy.run_baseline(cfg, seg, feat, dfx, np.random.default_rng(0)); print("baseline total", time.perf_counter()-t)
# crack detection in baseline via CML
cfgp = params.load_config()
r = strategy.run_baseline(cfg, seg, feat, dfx, np.random.default_rng(0))
print("baseline crack det rate", r["detection_rate_crack"])
d = strategy._prepare(cfg, seg, dfx)
print("critical cracks", int((d.kind.eq("crack") & d.critical).sum()))
