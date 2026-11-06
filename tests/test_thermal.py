import copy
import itertools

import numpy as np
import pytest

from maek import params, thermal
from maek import thermal_render as tr
from maek.camera import composite2d


def test_h3_existing_thermal_dataset(cfg, tmp_path):
    jobs = tr.make_ir_jobs(cfg, 2, 1, "train")
    tr.render_all_ir(cfg, jobs, tmp_path, seed=1)
    before = sorted(p.name for p in (tmp_path / "images").iterdir())
    with pytest.raises(FileExistsError):
        tr.render_all_ir(cfg, jobs[:1], tmp_path, seed=1)
    assert sorted(p.name for p in (tmp_path / "images").iterdir()) == before

SEG = {"medium": "steam", "material": "carbon_steel", "temp_c": 180.0, "od_mm": 114.3,
       "insulated": True, "insulation_mm": 50.0, "jacket": "aluminium", "pressure_barg": 8.0,
       "traced": False}


@pytest.fixture(scope="module")
def cfg():
    return params.load_config()


def _job(cfg, defects, eps_j=0.25, eps_set=0.25, sky=-3.0, **kw):
    sc = {"ambient_c": 15.0, "sky_offset_k": sky, "wind_mps": 1.0, "sun_k": 0.0,
          "eps_jacket": eps_j, "eps_set": eps_set, "hw_px": 36.0, "tilt_deg": 4.0,
          "cy_px": 128.0, "blur_sigma": 0.8, "bare_eps": 0.8}
    sc.update(kw)
    return {"job_id": "t", "segment_id": "t", "condition": "train", "image_w": 320,
            "image_h": 256, "negative": not defects, "seg": dict(SEG), "scene": sc, "hard": [],
            "distractors": [], "defects": defects}


def _wet(cfg, moisture=0.8, u=0.0):
    d = {"kind": "wet_insulation", "class_id": 1, "u": u, "a_px": 14.0, "v": 14.0, "b_px": 18.0,
         "moisture": moisture, "soft": 0.35}
    d["true_dt_k"] = thermal.contrast_k(cfg, SEG, d, 1.0, 15.0)
    return d


def test_wet_zone_warmer_and_grows_with_moisture(cfg):
    c = [thermal.contrast_k(cfg, SEG, {"kind": "wet_insulation", "moisture": m})
         for m in (0.1, 0.4, 0.8)]
    assert c[0] > 0 and c[0] < c[1] < c[2]
    assert thermal.contrast_k(cfg, SEG, {"kind": "tracer_leak"}) == pytest.approx(
        thermal.contrast_k(cfg, SEG, {"kind": "wet_insulation", "moisture": 0.8}))
    assert thermal.contrast_k(cfg, SEG, {"kind": "trap_failed_open"}) == 0.0
    dry = dict(SEG, insulated=False)
    assert thermal.contrast_k(cfg, dry, {"kind": "wet_insulation", "moisture": 0.8}) == 0.0


def test_low_emissivity_shrinks_apparent_contrast(cfg):
    dt = thermal.contrast_k(cfg, SEG, {"kind": "wet_insulation", "moisture": 0.8})
    tj = thermal.jacket_temp_c(cfg, SEG)
    app = {}
    for eps in (0.08, 0.3):
        a0 = thermal.apparent_temp_c(tj, eps, 15.0, 0.3, 15.0)
        a1 = thermal.apparent_temp_c(tj + dt, eps, 15.0, 0.3, 15.0)
        app[eps] = float(a1 - a0)
    assert 0 < app[0.08] < app[0.3] <= dt * 1.05


def test_render_deterministic_and_classes(cfg):
    jobs = tr.make_ir_jobs(cfg, 12, 3, "train")
    assert any(j["defects"] for j in jobs) and any(not j["defects"] for j in jobs)
    for j in jobs[:6]:
        a = tr.render_ir(cfg, j, np.random.default_rng(4))
        b = tr.render_ir(cfg, j, np.random.default_rng(4))
        assert a[0].tobytes() == b[0].tobytes() and a[1].tobytes() == b[1].tobytes()
        assert a[0].shape == (256, 320) and a[0].dtype == np.float32
        assert a[1].dtype == np.uint8 and set(np.unique(a[1])) <= {0, 1, 2, 3}


def test_detector_finds_wet_zone_and_clean_scene_is_empty(cfg):
    job = _job(cfg, [_wet(cfg)])
    temp, mask = tr.render_ir(cfg, job, np.random.default_rng(1))
    pred = tr.detect_ir(cfg, temp, tr.pipe_mask(job))
    assert mask.sum() > 0
    assert ((pred == 1) & (mask == 1)).sum() > 0.3 * (mask == 1).sum()
    clean = _job(cfg, [])
    empty = 0
    for seed in range(6):     # emissivity clutter may rarely give a small false blob
        temp, mask = tr.render_ir(cfg, clean, np.random.default_rng(seed))
        assert not mask.any()
        empty += not tr.detect_ir(cfg, temp, tr.pipe_mask(clean)).any()
    assert empty >= 5


def test_detect_prob_monotone_and_reviewer(cfg):
    ps = [thermal.detect_prob(cfg, SEG, {"kind": "wet_insulation", "moisture": m})
          for m in (0.05, 0.2, 0.5, 1.0)]
    assert all(b >= a for a, b in itertools.pairwise(ps)) and ps[-1] > ps[0]
    os_ = [thermal.detect_prob(cfg, SEG, {"kind": "steam_leak", "orifice_mm": o}, "shifted")
           for o in (1, 3, 10, 25)]
    assert all(b > a for a, b in itertools.pairwise(os_))
    d = {"kind": "wet_insulation", "moisture": 0.5}
    assert thermal.detect_prob(cfg, SEG, d, reviewer="human") == pytest.approx(
        0.6 * thermal.detect_prob(cfg, SEG, d))
    assert thermal.detect_prob(cfg, dict(SEG, insulated=False), d) == 0.0
    assert thermal.detect_prob(cfg, dict(SEG, insulated=False),
                               {"kind": "steam_leak", "orifice_mm": 10}) > 0
    assert thermal.detect_prob(cfg, SEG, {"kind": "trap_failed_open"}) > 0


def test_trap_rule(cfg):
    for cond in ("train", "shifted"):
        t = thermal.trap_pods(cfg, cond, n=1500, seed=0)
        assert t["pod_closed"] > t["false_alarm"] and t["pod_open"] > t["false_alarm"]
        assert t["false_alarm"] < 0.1


def test_camera_yolo_lines_unchanged_by_generalisation():
    m = np.zeros((40, 50), np.uint8)
    m[5:20, 5:25] = 1
    m[25:35, 30:45] = 3
    assert composite2d.yolo_lines(m) == composite2d.yolo_lines(m, classes=composite2d.CLASSES)
    ir = composite2d.yolo_lines(m, tr.IR_CLASSES)
    assert [ln.split()[0] for ln in ir] == ["0", "2"]


def test_render_all_ir_outputs(cfg, tmp_path):
    c = copy.deepcopy(cfg)
    jobs = tr.make_ir_jobs(c, 6, 5, "shifted")
    ds = tr.render_all_ir(c, jobs, tmp_path, seed=1)
    assert ds.exists() and (tmp_path / "jobs.json").exists()
    from PIL import Image

    im = np.asarray(Image.open(tmp_path / "images" / f"{jobs[0]['job_id']}.png"))
    assert im.dtype == np.uint16 and im.shape == (256, 320)
    assert "wet_insulation" in ds.read_text()


def test_evaluate_and_fit_small(cfg):
    met, df = tr.evaluate_ir(cfg, 40, 2, "train")
    assert 0 <= met["fp_per_image"] < 5 and {"class", "a", "hit"} <= set(df.columns)
    fit = tr.fit_ir_pod(cfg, df=df)
    assert set(fit) == {"wet_insulation", "insulation_damage", "steam_leak"}
