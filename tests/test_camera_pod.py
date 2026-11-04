import copy
import json

import numpy as np
import pytest

from maek import network, params, pod
from maek.camera import composite2d, jobs


@pytest.fixture(scope="module")
def cfg():
    c = copy.deepcopy(params.load_config())
    c["camera"]["image_size"]["value"] = 256
    return c


@pytest.fixture(scope="module")
def net(cfg):
    return network.generate_network(cfg, seed=3, total_km=8)


@pytest.fixture(scope="module")
def jl(cfg, net):
    return jobs.make_jobs(cfg, net[0], net[2], 60, seed=1)


def _corr_job(area_px_frac, cfg):
    d = {"defect_id": "D", "kind": "external_corrosion", "class_id": 1, "area_cm2": 10.0,
         "u": 0.5, "v": 0.0, "w": area_px_frac, "h": area_px_frac}
    return {"job_id": "X", "segment_id": "S", "image_size": 256, "negative": False,
            "pipe": {"od_mm": 200.0, "material": "carbon_steel", "insulated": False,
                     "width_frac": 0.6, "tilt_deg": 5.0, "view_center_m": 0, "view_clock_deg": 0},
            "defects": [d],
            "env": {"brightness": 1.0, "dust": 0.1, "steam": 0.1, "blur_sigma": 1.0,
                    "noise_sigma": 0.01}}


def test_jobs_roundtrip_and_mix(tmp_path, jl):
    p = jobs.save_jobs(tmp_path / "jobs.json", jl)
    assert jobs.load_jobs(p) == json.loads(json.dumps(jl))
    neg = [j for j in jl if j["negative"]]
    assert 0.25 < len(neg) / len(jl) < 0.7
    assert all(not j["defects"] for j in neg)
    assert any(j["defects"] for j in jl)


def test_deterministic_render(cfg, jl):
    job = next(j for j in jl if j["defects"])
    a = composite2d.render_job(cfg, job, np.random.default_rng(5))
    b = composite2d.render_job(cfg, job, np.random.default_rng(5))
    assert a[0].tobytes() == b[0].tobytes() and a[1].tobytes() == b[1].tobytes()
    assert a[0].shape == (256, 256, 3) and a[0].dtype == np.uint8


def test_mask_area_grows_with_defect_size(cfg):
    areas = []
    for s in (0.06, 0.12, 0.24):
        rng = np.random.default_rng(0)
        _, m = composite2d.render_job(cfg, _corr_job(s, cfg), rng)
        areas.append(int((m == 1).sum()))
    assert areas[0] < areas[1] < areas[2]


def test_negative_masks_empty(cfg, jl):
    for j in [j for j in jl if j["negative"]][:5]:
        _, m = composite2d.render_job(cfg, j, np.random.default_rng(1))
        assert not m.any()


def test_render_all_yolo(cfg, jl, tmp_path):
    ds = composite2d.render_all(cfg, jl[:12], tmp_path, seed=2)
    assert ds.exists()
    n_poly = 0
    for j in jl[:12]:
        assert (tmp_path / "images" / f"{j['job_id']}.png").exists()
        lab = tmp_path / "labels" / f"{j['job_id']}.txt"
        assert lab.exists()
        for line in lab.read_text().splitlines():
            parts = line.split()
            assert int(parts[0]) in (0, 1, 2)
            vals = np.array(parts[1:], float)
            assert len(vals) >= 6 and len(vals) % 2 == 0
            assert vals.min() >= 0 and vals.max() <= 1
            n_poly += 1
    assert n_poly > 0


def test_contour_square():
    m = np.zeros((20, 20), np.uint8)
    m[5:12, 4:15] = 1
    polys = list(composite2d.mask_polygons(m))
    assert len(polys) == 1
    pts = polys[0][1]
    assert pts[:, 0].min() == 4 and pts[:, 0].max() == 14
    assert pts[:, 1].min() == 5 and pts[:, 1].max() == 11


def test_pod_fit_recovers_params():
    rng = np.random.default_rng(0)
    b0, b1 = -1.5, 2.2
    a = rng.uniform(0.2, 4.0, 3000)
    hits = rng.random(3000) < pod.pod(a, b0, b1)
    f = pod.fit_pod(a, hits)
    assert abs(f["b0"] - b0) / abs(b0) < 0.15
    assert abs(f["b1"] - b1) / b1 < 0.15
    a90, lo, hi = pod.bootstrap_a90(a, hits, n_boot=100, seed=1)
    assert lo <= a90 <= hi
    assert abs(a90 - pod.a_at(0.9, b0, b1)) / pod.a_at(0.9, b0, b1) < 0.15


def test_a_at_median():
    assert pod.a_at(0.5, -1.5, 2.2) == pytest.approx(np.exp(1.5 / 2.2))
    assert pod.pod(pod.a_at(0.9, 0.3, 1.1), 0.3, 1.1) == pytest.approx(0.9)
