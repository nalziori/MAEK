"""Copy report figures into the repo folder; photos and screenshots become JPEG to keep the document small.

    python prep_fig.py <source fig dir> <destination fig dir>
"""
import os
import shutil
import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for f in ("corrosion_curve.png", "site_specific.png", "thermal_curve.png", "feedback_arms.png"):
    shutil.copy(os.path.join(src, f), dst)
for f in ("examples_corrosion.png", "examples_thermal.png", "shot_try.png", "shot_sim.png"):
    im = Image.open(os.path.join(src, f)).convert("RGB")
    im.thumbnail((1800, 3600))
    im.save(os.path.join(dst, f.replace(".png", ".jpg")), quality=88)
print(sorted((f, os.path.getsize(os.path.join(dst, f)) // 1024) for f in os.listdir(dst)))
