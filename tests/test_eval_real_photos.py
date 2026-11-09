import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_real_photos as er


def test_real_photo_eval_polygon_box_and_negatives(tmp_path):
    img, lab = tmp_path / "set" / "images", tmp_path / "set" / "labels"
    img.mkdir(parents=True)
    lab.mkdir()
    rgb = np.full((100, 100, 3), 128, np.uint8)
    rgb[20:60, 20:60] = (200, 100, 30)  # orange rust patch: HSV baseline marks it corrosion
    Image.fromarray(rgb).save(img / "a.png")
    Image.fromarray(np.full((100, 100, 3), 128, np.uint8)).save(img / "b.png")  # clean
    (lab / "a.txt").write_text("0 0.2 0.2 0.6 0.2 0.6 0.6 0.2 0.6\n1 0.85 0.85 0.1 0.1\n")
    out = tmp_path / "o"
    assert er.main(["--images", str(img), "--map", "0=corrosion", "--map", "1=leak_stain",
                    "--method", "hsv", "--vis", "1", "--out", str(out)]) == 0
    o = __import__("pandas").read_csv(out / "objects.csv")
    rust = o[o["class"] == "corrosion"].iloc[0]
    assert rust["shape"] == "polygon" and rust["detected"] and rust["coverage"] > 0.9
    assert not o[o["class"] == "leak_stain"].iloc[0]["detected"]
    assert (out / "vis" / "a.jpg").exists()
    assert er.main(["--images", str(img), "--negatives", "--method", "hsv", "--out", str(tmp_path / "n")]) == 0
    s = __import__("pandas").read_csv(tmp_path / "n" / "summary.csv")
    assert s.loc[s["class"] == "corrosion", "false_alarm"].item() == 0.5  # a.png's rust counts as an alarm
