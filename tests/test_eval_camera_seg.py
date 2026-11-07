import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_camera_seg as ev
import make_dr_camera as dr


def test_dr_dataset_then_defect_level_eval(tmp_path):
    out = tmp_path / "dr"
    dr.main(["--out", str(out), "--n", "6", "--seed", "12", "--workers", "1"])
    assert (out / "jobs.json").exists() and (out / "dataset.yaml").exists()
    assert ev.main(["--data", str(out), "--seed", "12", "--method", "hsv", "--out", str(tmp_path / "e")]) == 0
    s = (tmp_path / "e" / "summary.csv").read_text()
    assert "corrosion" in s and "leak_stain" in s
    assert ev.main(["--data", str(out), "--seed", "12", "--method", "hsv", "--pre", "gamma",
                    "--save-pred", "--out", str(tmp_path / "g")]) == 0
    assert len(list((tmp_path / "g" / "pred").glob("*.png"))) == 6
    with pytest.raises(ValueError, match="wrong --seed"):  # ids must come from the same render seed
        ev.main(["--data", str(out), "--seed", "13", "--method", "hsv", "--out", str(tmp_path / "x")])
