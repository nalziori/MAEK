import sys
sys.path.insert(0, "/home/user/maek")
import numpy as np
from maek.camera import composite2d as c

# start pixel is a cut vertex: top pixel with branches SW and SE
m = np.zeros((12, 12), bool)
m[1, 5] = True
for k in range(1, 6):
    m[1 + k, 5 - k] = True   # SW diagonal arm
    m[1 + k, 5 + k] = True   # SE diagonal arm
pts = c.trace_contour(m)
print("V shape pixels", m.sum(), "contour pts", len(pts), pts)

# blob with a thin arm hanging off the top-left pixel going down-left
m2 = np.zeros((20, 20), bool)
m2[2, 8] = True
m2[3, 7] = True; m2[4, 6] = True
m2[3:10, 9:15] = True
pts2 = c.trace_contour(m2)
xs = [p[0] for p in pts2]; ys=[p[1] for p in pts2]
print("blob+arm: contour pts", len(pts2), "x range", min(xs), max(xs), "y range", min(ys), max(ys))
print("true x range", np.nonzero(m2)[1].min(), np.nonzero(m2)[1].max(), "y", np.nonzero(m2)[0].min(), np.nonzero(m2)[0].max())
