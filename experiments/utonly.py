import sys, time
from maek import params, evaluate as ev
cfg = params.load_config()
n, nf = int(sys.argv[1]), int(sys.argv[2])
t = time.time()
res = {"ut": {c: ev.eval_ut(cfg, c, n, 0) for c in ev.CONDITIONS}}
print("eval_ut", time.time() - t, flush=True)
res["pit_ablation"] = ev.pit_ablation(cfg, n, 0); print("ablation", time.time() - t, flush=True)
res["pit_factors"] = ev.pit_factors(cfg, nf, 0); print("factors", time.time() - t, flush=True)
res["meta"] = {"avg_extra_time_s": params.get(cfg, "ut.avg_extra_time_s")}
print("\n\n".join(ev.pit_tables_markdown(res)))
for c in ev.CONDITIONS:
    u = res["ut"][c]
    print(c, {k: round(v, 4) for k, v in u.items() if isinstance(v, float)})
