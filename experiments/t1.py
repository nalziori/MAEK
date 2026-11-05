import time
from maek import params, strategy
cfg = params.load_config()
t=time.time()
c = strategy.compare(cfg, 1, 2, 10.0)
print(time.time()-t)
print(strategy.to_markdown(c))
